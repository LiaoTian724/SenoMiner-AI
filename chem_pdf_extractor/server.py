from __future__ import annotations

import json
import os
import secrets
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
import webbrowser

from .config import (
    PROJECT_ROOT,
    DEFAULT_CLOUD_BASE_URL,
    DEFAULT_CLOUD_MODEL,
    DEFAULT_MAX_CHARS,
    DEFAULT_MODEL,
    DEFAULT_NUM_CTX,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_PDF_MODE,
    PDF_MODE_CHOICES,
    BAD_ROW_MIN_FILL_RATE,
    RuntimeDeps,
    apply_cloud_config_defaults,
    default_input_dir,
    default_output_path,
    delete_cloud_profile,
    load_local_config,
    mask_api_key,
    public_local_config,
    save_local_config,
    validate_cloud_test_config,
    validate_cloud_start_config,
)
from .diagnostics import append_diagnostic_log, log_exception, log_startup_event
from .extractor import JobState, run_extraction_job, state_update
from .llm import choose_model, fetch_openai_compatible_models, get_ollama_models, test_openai_compatible_chat
from .security import redact_sensitive_text
from .text_safety import json_dumps_utf8
from . import catalog
from .catalog_progress import CatalogProgress
from .sources import normalize_identifier

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def render_catalog_html(token: str) -> str:
    return (TEMPLATES_DIR / "catalog.html").read_text(encoding="utf-8").replace(
        "__LOCAL_TOKEN__", json_dumps_utf8(token))


def allowed_ui_origins(port: int) -> set[str]:
    return {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}


def is_loopback_client(address: Any) -> bool:
    host = str(address[0] if isinstance(address, tuple) and address else address)
    return host in {"127.0.0.1", "::1", "localhost"}


def is_allowed_origin_header(value: str | None, port: int) -> bool:
    if not value:
        return True
    cleaned = value.strip().rstrip("/")
    return cleaned in allowed_ui_origins(port)


def is_allowed_referer_header(value: str | None, port: int) -> bool:
    if not value:
        return True
    return any(value.strip().startswith(origin + "/") or value.strip() == origin for origin in allowed_ui_origins(port))


def validate_local_api_request(
    *, token: str | None, expected_token: str, client_address: Any,
    origin: str | None, referer: str | None, port: int,
) -> bool:
    if not expected_token or not secrets.compare_digest(str(token or ""), expected_token):
        return False
    if not is_loopback_client(client_address):
        return False
    if not is_allowed_origin_header(origin, port):
        return False
    if not is_allowed_referer_header(referer, port):
        return False
    return True


def sanitize_cloud_test_error(error: Any, api_key: str = "") -> str:
    text = redact_sensitive_text(str(error))
    raw_key = str(api_key or "").strip()
    if raw_key:
        text = text.replace(raw_key, "<redacted>")
    return text


def run_cloud_api_test(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("base_url") and not config.get("cloud_base_url"):
        config["cloud_base_url"] = config.get("base_url")
    if config.get("api_key") and not config.get("cloud_api_key"):
        config["cloud_api_key"] = config.get("api_key")
    if config.get("model") and not config.get("cloud_model"):
        config["cloud_model"] = config.get("model")
    apply_cloud_config_defaults(config)
    api_key = str(config.get("api_key") or config.get("cloud_api_key") or "").strip()
    payload = {
        "api_key": api_key,
        "base_url": str(config.get("base_url") or config.get("cloud_base_url") or "").strip(),
        "model": str(config.get("model") or config.get("cloud_model") or "").strip(),
    }
    validation_error = validate_cloud_test_config(payload)
    if validation_error:
        return {"ok": False, "status": "failed", "error": sanitize_cloud_test_error(validation_error, api_key)}

    try:
        test_openai_compatible_chat(payload["base_url"], api_key, payload["model"], timeout=10.0)
    except Exception as exc:
        return {"ok": False, "status": "failed", "error": sanitize_cloud_test_error(exc, api_key)}

    try:
        models = fetch_openai_compatible_models(payload["base_url"], api_key, timeout=5.0)
    except Exception as exc:
        return {
            "ok": True,
            "status": "partial",
            "message": "Connection works, but model list is unavailable; manual model may be needed.",
            "detail": sanitize_cloud_test_error(exc, api_key),
        }

    return {
        "ok": True,
        "status": "success",
        "message": "Connection works and model returned valid response.",
        "models_available": True,
        "model_count": len(models),
    }


class ChemExtractorApp:
    def __init__(self, runtime: RuntimeDeps, default_pdf_mode: str = DEFAULT_PDF_MODE) -> None:
        self.runtime = runtime
        self.default_pdf_mode = default_pdf_mode if default_pdf_mode in PDF_MODE_CHOICES else DEFAULT_PDF_MODE
        self.state = JobState()
        self.server: ThreadingHTTPServer | None = None
        self.ui_token = secrets.token_urlsafe(32)
        self.port = 0
        self.catalog_task = CatalogProgress()
        self.instance_id = ""

    def catalog_status(self) -> dict[str, Any]:
        return self.catalog_task.snapshot()

    def catalog_log(self, message: str) -> None:
        self.catalog_task.log(message)



class RequestHandler(BaseHTTPRequestHandler):
    app: ChemExtractorApp

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_common_security_headers(self, *, html: bool = False) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        if html:
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'self'",
            )

    def protected_api_request_is_valid(self) -> bool:
        return validate_local_api_request(
            token=self.headers.get("X-Chem-PDF-Extractor-Token"),
            expected_token=self.app.ui_token,
            client_address=self.client_address,
            origin=self.headers.get("Origin"),
            referer=self.headers.get("Referer"),
            port=self.app.port,
        )

    def reject_forbidden(self) -> None:
        self.send_json({"ok": False, "error": "forbidden"}, status=403)

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        data = json_dumps_utf8(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_common_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8", errors="replace"))

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/local-instance":
            if not is_loopback_client(self.client_address) or not is_allowed_origin_header(self.headers.get("Origin"), self.app.port):
                self.reject_forbidden()
                return
            self.send_json({"instance_id": self.app.instance_id})
            return
        if parsed.path == "/catalog":
            data = render_catalog_html(self.app.ui_token).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_common_security_headers(html=True)
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path in {"/static/3Dmol-min.js", "/static/catalog.js", "/static/catalog.css"}:
            data = (Path(__file__).resolve().parent / "static" / parsed.path.rsplit("/", 1)[-1]).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8" if parsed.path.endswith(".css") else "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_common_security_headers()
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path in {"/", "/showcase"}:
            # Old bookmarks go to the single input/progress/results page.
            self.send_response(303)
            self.send_header("Location", "/catalog")
            self.send_header("Content-Length", "0")
            self.send_common_security_headers()
            self.end_headers()
            return

        if parsed.path.startswith("/api/") and not self.protected_api_request_is_valid():
            self.reject_forbidden()
            return

        if parsed.path == "/api/catalog":
            self.send_json({**catalog.build_catalog(), **self.app.catalog_status()})
            return

        if parsed.path == "/api/catalog/records":
            from .experimental_records import all_records, records_csv, filter_records
            query = urllib.parse.parse_qs(parsed.query)
            try:
                records = filter_records(all_records(catalog.build_catalog()), query.get("q", [""])[0],
                                         query.get("study_type", [""])[0], query.get("effect_type", [""])[0])
            except ValueError as exc:
                self.send_json({"ok":False, "error":str(exc)}, status=400)
                return
            if query.get("format", [""])[0] == "csv":
                data = records_csv(records)
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="experiment-records.csv"')
                self.send_header("Content-Length", str(len(data)))
                self.send_common_security_headers()
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_json({"ok":True, "records":records, "count":len(records)})
            return

        if parsed.path == "/api/catalog/search":
            query = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
            try:
                self.send_json({"ok": True, "papers": catalog.search_pubmed(query)})
            except Exception as exc:
                self.send_json({"ok": False, "error": redact_sensitive_text(str(exc))}, status=400)
            return

        if parsed.path == "/api/catalog/structure":
            cid = urllib.parse.parse_qs(parsed.query).get("cid", [""])[0]
            try:
                self.send_json({"ok": True, **catalog.structure_details(cid)})
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=404)
            return

        if parsed.path == "/api/status":
            self.send_json(self.app.state.snapshot())
            return

        if parsed.path == "/api/models":
            # GET /api/models is for local Ollama model discovery.
            query = urllib.parse.parse_qs(parsed.query)
            base_url = query.get("base_url", [DEFAULT_OLLAMA_BASE_URL])[0]
            try:
                models = get_ollama_models(base_url)
                self.send_json({"ok": True, "models": models, "default_model": choose_model(DEFAULT_MODEL, models)})
            except Exception as exc:
                self.send_json({"ok": False, "error": redact_sensitive_text(str(exc)), "models": []}, status=200)
            return

        if parsed.path == "/api/config":
            self.send_json({"ok": True, "config": public_local_config()})
            return

        if parsed.path == "/api/init-config":
            local_config = load_local_config()
            raw_key = local_config.get("cloud_api_key") or os.environ.get("CHEM_PDF_EXTRACTOR_API_KEY") or os.environ.get("CHEM_EXTRACTOR_CLOUD_API_KEY") or ""
            self.send_json({"ok": True, "cloud_api_key_prefix": mask_api_key(raw_key), "config": public_local_config()})
            return

        self.send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/") and not self.protected_api_request_is_valid():
            self.reject_forbidden()
            return
        if parsed.path == "/api/catalog/import":
            try:
                payload = self.read_json()
                identifier = normalize_identifier(str(payload.get("identifier") or payload.get("pmid") or ""))
            except (ValueError, TypeError, AttributeError) as exc:
                self.send_json({"ok": False, "error": str(exc) if isinstance(exc, ValueError) else "无效请求"}, status=400)
                return
            if not self.app.catalog_task.start(identifier, "identifier"):
                self.send_json({"ok": False, "error": "已有文献正在处理，请查看提取进展"}, status=409)
                return
            threading.Thread(target=_run_catalog_import, args=(self.app, identifier), daemon=True).start()
            self.send_json({"ok": True, **self.app.catalog_status()})
            return
        if parsed.path == "/api/catalog/process-pdf":
            try:
                name = str(self.read_json().get("name") or "")
                output = catalog.local_pdf_output(name)
            except (ValueError, TypeError):
                self.send_json({"ok": False, "error": "无效 PDF 文件名"}, status=400)
                return
            pdf = PROJECT_ROOT / "input_pdfs" / name
            if not pdf.is_file():
                self.send_json({"ok": False, "error": "PDF 不在 input_pdfs 目录中"}, status=404)
                return
            if not self.app.catalog_task.start(name, "pdf"):
                self.send_json({"ok": False, "error": "已有文献正在处理，请查看提取进展"}, status=409)
                return
            threading.Thread(target=_run_catalog_pdf, args=(self.app, pdf, output), daemon=True).start()
            self.send_json({"ok": True, **self.app.catalog_status()})
            return
        if parsed.path == "/api/catalog/upload-pdf":
            name = urllib.parse.parse_qs(parsed.query).get("name", [""])[0]
            try:
                catalog.local_pdf_output(name)
                length = int(self.headers.get("Content-Length", "0"))
                if not 8 <= length <= 30_000_000:
                    raise ValueError("PDF 大小须在 8 字节至 30 MB 之间")
                payload = self.rfile.read(length)
                if len(payload) != length or not payload.startswith(b"%PDF-"):
                    raise ValueError("文件不是有效的 PDF")
                directory = PROJECT_ROOT / "input_pdfs"
                directory.mkdir(exist_ok=True)
                with (directory / name).open("xb") as stream:
                    stream.write(payload)
                self.send_json({"ok": True, "name": name})
            except FileExistsError:
                self.send_json({"ok": False, "error": "同名 PDF 已存在；请先在目录中查看"}, status=409)
            except (ValueError, OSError) as exc:
                self.send_json({"ok": False, "error": redact_sensitive_text(str(exc))}, status=400)
            return
        if parsed.path == "/api/config":
            try:
                config = self.read_json()
                if bool(config.get("clear_cloud_api_key", False)):
                    config["api_key"] = ""
                    config["cloud_api_key"] = ""
                save_local_config(config)
                self.send_json({"ok": True, "config": public_local_config()})
            except Exception as exc:
                self.send_json({"ok": False, "error": redact_sensitive_text(str(exc))})
            return

        if parsed.path == "/api/cloud-profiles/delete":
            try:
                config = self.read_json()
                profile_id = str(
                    config.get("profile_id")
                    or config.get("active_cloud_profile_id")
                    or config.get("cloud_profile_id")
                    or ""
                ).strip()
                if not profile_id:
                    self.send_json({"ok": False, "error": "Missing cloud profile id."}, status=400)
                    return
                if not delete_cloud_profile(profile_id):
                    self.send_json({"ok": False, "error": "Cloud profile not found."}, status=404)
                    return
                self.send_json({"ok": True, "config": public_local_config()})
            except Exception as exc:
                self.send_json({"ok": False, "error": redact_sensitive_text(str(exc))})
            return

        if parsed.path == "/api/cloud-test":
            try:
                self.send_json(run_cloud_api_test(self.read_json()))
            except Exception as exc:
                self.send_json({"ok": False, "status": "failed", "error": redact_sensitive_text(str(exc))})
            return

        if parsed.path in {"/api/cloud-models", "/api/models"}:
            # POST /api/cloud-models is the preferred OpenAI-compatible model discovery endpoint.
            # POST /api/models is kept as a compatibility alias for older frontends.
            try:
                config = self.read_json()
                if config.get("base_url") and not config.get("cloud_base_url"):
                    config["cloud_base_url"] = config.get("base_url")
                if config.get("api_key") and not config.get("cloud_api_key"):
                    config["cloud_api_key"] = config.get("api_key")
                apply_cloud_config_defaults(config)
                base_url = str(config.get("base_url") or config.get("cloud_base_url") or DEFAULT_CLOUD_BASE_URL).strip()
                api_key = str(config.get("api_key") or config.get("cloud_api_key") or "").strip()
                models = fetch_openai_compatible_models(base_url, api_key)
                default_model = DEFAULT_CLOUD_MODEL if DEFAULT_CLOUD_MODEL in models else models[0]
                self.send_json({"ok": True, "models": models, "default_model": default_model})
            except Exception as exc:
                self.send_json({"ok": False, "error": redact_sensitive_text(str(exc)), "models": []}, status=200)
            return

        if parsed.path == "/api/start":
            if self.app.state.snapshot()["running"]:
                self.send_json({"ok": False, "error": "已有任务正在运行"})
                return
            try:
                config = self.read_json()
                config.setdefault("input_dir", str(default_input_dir()))
                config.setdefault("output_path", str(default_output_path()))
                config.setdefault("llm_provider", "cloud")
                config.setdefault("model", DEFAULT_MODEL)
                config.setdefault("translate_to_chinese", True)
                config.setdefault("pdf_mode", self.app.default_pdf_mode)
                if str(config.get("pdf_mode") or "") not in PDF_MODE_CHOICES:
                    self.send_json({"ok": False, "error": f"Unsupported PDF mode: {config.get('pdf_mode')}"})
                    return
                config.setdefault("max_chars", DEFAULT_MAX_CHARS)
                config.setdefault("num_ctx", DEFAULT_NUM_CTX)
                config.setdefault("llm_timeout", 0)
                config.setdefault("bad_row_min_fill_percent", int(BAD_ROW_MIN_FILL_RATE * 100))
                config.setdefault("ollama_base_url", DEFAULT_OLLAMA_BASE_URL)
                apply_cloud_config_defaults(config)
                config.setdefault("recursive", True)
                config.setdefault("auto_fallback", False)
                if str(config.get("llm_provider") or "cloud") == "cloud":
                    selected_cloud_model = str(config.get("cloud_model") or config.get("model") or "").strip()
                    if not selected_cloud_model:
                        selected_cloud_model = DEFAULT_CLOUD_MODEL
                    config["cloud_model"] = selected_cloud_model
                    config["model"] = selected_cloud_model
                    validation_error = validate_cloud_start_config(config)
                    if validation_error:
                        self.send_json({"ok": False, "error": validation_error})
                        return
                    if not bool(config.get("cloud_active", False)):
                        self.send_json({"ok": False, "error": '请先勾选"激活此配置"，再使用云端 API。'})
                        return
                thread = threading.Thread(target=_run_extraction_job_with_logging, args=(config, self.app.runtime, self.app.state), daemon=True)
                thread.start()
                self.send_json({"ok": True})
            except Exception as exc:
                self.send_json({"ok": False, "error": redact_sensitive_text(str(exc))})
            return

        if parsed.path == "/api/stop":
            self.app.state.request_stop()
            self.send_json({"ok": True})
            return

        if parsed.path == "/api/pause":
            self.app.state.request_pause()
            self.send_json({"ok": True})
            return

        if parsed.path == "/api/resume":
            self.app.state.request_resume()
            self.send_json({"ok": True})
            return

        if parsed.path == "/api/shutdown":
            self.app.state.request_stop()
            self.send_json({"ok": True})
            if self.app.server is not None:
                threading.Thread(target=self.app.server.shutdown, daemon=True).start()
            return

        self.send_json({"ok": False, "error": "not found"}, status=404)


def find_free_port(preferred_port: int) -> int:
    candidates = list(range(preferred_port, preferred_port + 50)) + [0]
    last_error: OSError | None = None
    for port in candidates:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", port))
                return int(sock.getsockname()[1])
        except OSError as exc:
            last_error = exc
            continue
    raise RuntimeError(f"无法找到可用本地端口，最后一次错误：{last_error}")


def _run_extraction_job_with_logging(config: dict[str, Any], runtime: RuntimeDeps, state: JobState) -> None:
    try:
        run_extraction_job(config, runtime, state)
    except Exception as exc:
        log_exception(exc, context="background_extraction_thread")
        try:
            state.add_log("后台任务异常，详见 logs/crash.log")
            state_update(state, running=False, message="任务异常，详见 logs/crash.log")
        except Exception:
            pass


def _catalog_config(app: ChemExtractorApp) -> dict:
    model = os.getenv("CHEM_PDF_EXTRACTOR_MODEL") or os.getenv("ARK_MODEL_ID") or ""
    base_url = os.getenv("CHEM_PDF_EXTRACTOR_BASE_URL") or os.getenv("ARK_BASE_URL") or ""
    api_key = os.getenv("CHEM_PDF_EXTRACTOR_API_KEY") or os.getenv("ARK_API_KEY") or ""
    if not all((model, base_url, api_key)):
        raise ValueError("云端模型配置不完整，请检查 .env")
    return {"llm_provider": "cloud", "cloud_api_key": api_key,
            "cloud_base_url": base_url, "cloud_model": model, "model": model,
            "llm_timeout": 240, "chunk_size": 8000, "workers": 3,
            "enrich_databases": True, "literature_limit": 3, "log": app.catalog_log,
            "progress": app.catalog_task.update}


def _catalog_report_complete(output: Path) -> bool:
    from .claim_review import load_review
    from .evidence_cards import load_cards
    try:
        report = json.loads((output / "report.json").read_text())
        source = (output / "source.md").read_text()
        rows = report.get("records", [])
        review = load_review(output, rows, source)
        return review.get("status") == "complete" and load_cards(output, rows, source, review) is not None
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def _catalog_check_stages(output: Path) -> None:
    # These stages retain the raw report even when their model call failed.
    # Report a resumable failure, never turn a saved partial report into success.
    for name, label in (("claim_review.json", "全文核对"), ("evidence_cards.json", "实验关联")):
        try:
            saved = json.loads((output / name).read_text())
        except (OSError, ValueError):
            raise RuntimeError(f"原始提取已保存，但{label}结果缺失；请重试继续。") from None
        if saved.get("status") != "complete":
            raise RuntimeError(f"原始提取已保存，但{label}未完成：{saved.get('error') or '请重试继续'}")


def _catalog_completion_message(output: Path) -> str:
    """Distinguish no eligible findings from evidence that still needs review."""
    from .claim_review import load_review
    from .evidence_cards import load_cards
    report = json.loads((output / "report.json").read_text())
    rows = report.get("records", [])
    source = (output / "source.md").read_text()
    review = load_review(output, rows, source)
    cards = load_cards(output, rows, source, review)
    if cards is None:
        raise RuntimeError("实验关联尚未完成，请重试继续。")
    names = {c["name"] for c in cards}
    if names:
        return f"提取完成：收录 {len(names)} 个化合物、{len(cards)} 组实验。可在列表中查看。"
    decisions = review.get("decisions", [])
    accepted = sum(d.get("verdict") == "accepted" for d in decisions)
    uncertain = sum(d.get("verdict") == "uncertain" for d in decisions)
    if accepted:
        return f"提取结束：识别出 {accepted} 个有效候选，但未关联到可核对的完整实验，列表收录 0 个化合物；需复核。"
    if uncertain:
        return f"提取结束：列表收录 0 个化合物；{uncertain} 个候选的原文证据未通过核对，需复核。"
    return "提取完成：未找到符合收录条件的本篇实验结果，列表收录 0 个化合物。"


def _run_catalog_import(app: ChemExtractorApp, identifier: str) -> None:
    from .biomedical import extract_article
    from .sources import load_paper, resolve_pubmed_identifier
    from .science_skills import ScienceSkills
    needs_pdf = False
    error = ""
    completion_message = ""
    try:
        config = _catalog_config(app)
        app.catalog_task.update("loading", message=f"正在定位 {identifier} 并获取公开全文")
        skills = ScienceSkills(PROJECT_ROOT / "output" / ".search_cache")
        pmid = resolve_pubmed_identifier(identifier, skills)
        output = PROJECT_ROOT / "output" / "papers" / f"PMID-{pmid}"
        if _catalog_report_complete(output):
            completion_message = _catalog_completion_message(output)
            app.catalog_log(f"PMID {pmid} 已完成，无需重复提取")
            return
        paper = load_paper(f"PMID:{pmid}", skills, app.runtime)
        if paper.get("scope") != "oa_full_text":
            needs_pdf = True
            raise ValueError("已找到文献信息，但当前未取得公开全文（可能未开放或获取失败）。请上传该论文 PDF 后提取；不会用摘要代替全文。")
        app.catalog_log(f"已获取全文：{paper.get('title') or pmid}")
        rows = extract_article(paper, [], config, app.runtime, skills, output)
        _catalog_check_stages(output)
        completion_message = _catalog_completion_message(output)
        app.catalog_log(f"已完成：{len(rows)} 条原始候选；通过核对的结果已进入列表")
    except Exception as exc:
        log_exception(exc, context="catalog_import")
        error = redact_sensitive_text(str(exc))
    finally:
        app.catalog_task.finish(error, needs_pdf=needs_pdf, message=completion_message)


def _run_catalog_pdf(app: ChemExtractorApp, pdf: Path, output: Path) -> None:
    from .biomedical import extract_article
    from .sources import load_paper
    from .science_skills import ScienceSkills
    error = ""
    completion_message = ""
    try:
        config = _catalog_config(app)
        if _catalog_report_complete(output):
            completion_message = _catalog_completion_message(output)
            app.catalog_log(f"{pdf.name} 已完成，无需重复提取")
            return
        skills = ScienceSkills(output / "database_cache")
        app.catalog_task.update("loading", message=f"正在解析 {pdf.name}")
        paper = load_paper(str(pdf), skills, app.runtime)
        app.catalog_log(f"PDF 已解析，共 {len(paper['text'])} 字符")
        rows = extract_article(paper, [], config, app.runtime, skills, output)
        _catalog_check_stages(output)
        completion_message = _catalog_completion_message(output)
        app.catalog_log(f"已完成：{len(rows)} 条原始候选；通过核对的结果已进入列表")
    except Exception as exc:
        log_exception(exc, context="catalog_pdf")
        error = redact_sensitive_text(str(exc))
    finally:
        app.catalog_task.finish(error, message=completion_message)


def _serve_web_app(
    port: int,
    auto_install: bool,
    open_browser: bool = False,
    initial_pdf_mode: str = DEFAULT_PDF_MODE,
    instance=None,
) -> int:
    from .config import ensure_dependencies, import_runtime_dependencies
    log_startup_event(mode="web", extra={"requested_port": port, "open_browser": open_browser})
    server: ThreadingHTTPServer | None = None
    try:
        append_diagnostic_log("startup.log", "checking dependencies")
        ensure_dependencies(auto_install=auto_install)
        append_diagnostic_log("startup.log", "importing runtime dependencies")
        runtime = import_runtime_dependencies()
        app = ChemExtractorApp(runtime, default_pdf_mode=initial_pdf_mode)
        actual_port = find_free_port(port)
        app.port = actual_port
        app.instance_id = instance.instance_id if instance else ""
        server = ThreadingHTTPServer(("127.0.0.1", actual_port), RequestHandler)
        app.server = server
        RequestHandler.app = app
        if instance:
            instance.publish(actual_port)
        url = f"http://127.0.0.1:{actual_port}/catalog"
        append_diagnostic_log(
            "startup.log",
            f"local Web UI URL: {url}; selected port: {actual_port}; open_browser: {open_browser}",
        )
        print("Chem-PDF-Extractor 页面已启动：")
        print(url)
        if open_browser:
            webbrowser.open(url)
        else:
            print("请复制上面的地址到浏览器打开。")
        print('关闭浏览器标签页不会停止正在运行的本地服务；需要停止任务请点页面里的”停止任务”。')
        server.serve_forever()
        append_diagnostic_log("startup.log", "web server serve_forever ended")
    except Exception as exc:
        log_exception(exc, context="web_server")
        raise
    finally:
        if server is not None:
            server.server_close()
            append_diagnostic_log("startup.log", "web server closed")
            print("Chem-PDF-Extractor 本地服务已关闭。")
    return 0


def start_web_app(
    port: int,
    auto_install: bool,
    open_browser: bool = False,
    initial_pdf_mode: str = DEFAULT_PDF_MODE,
) -> int:
    from .single_instance import WebInstance
    instance = WebInstance(PROJECT_ROOT)
    try:
        if not instance.acquire():
            url = instance.existing_url()
            print("项目已在运行，使用现有页面：")
            print(url)
            if open_browser:
                webbrowser.open(url)
            return 0
        return _serve_web_app(port, auto_install, open_browser, initial_pdf_mode, instance=instance)
    finally:
        instance.close()
