from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import (
    CLOUD_RETRY_BASE_DELAY_SECONDS,
    CLOUD_RETRY_COUNT,
    CLOUD_RETRY_MAX_DELAY_SECONDS,
    DEFAULT_MODEL,
    RuntimeDeps,
    missing_rule,
    requirement_label,
    requirement_rule,
    short_error,
    validate_cloud_base_url_security,
)
from .biology import BIOLOGY_RULES
from .network import tls_context
from .security import redact_sensitive_text
from .text_safety import json_dumps_utf8


PROVENANCE_HINT_RULE = (
    " Review/provenance aid rule: never invent source_evidence, source_hint, "
    "page_hint, section_hint, table_hint, verification_status, or review_note. "
    "Use page_hint only from visible page markers, and use section_hint/table_hint "
    "only from clear headings, captions, tables, or nearby text. Leave provenance "
    "hints empty when unclear."
)


MALFORMED_JSON_WARNING = "malformed_json"
MISSING_RECORDS_WARNING = "missing_records"
SINGLE_OBJECT_FALLBACK_WARNING = "single_object_fallback"
NON_OBJECT_RECORD_WARNING = "non_object_record"
UNKNOWN_KEYS_WARNING = "unknown_keys"
TYPE_NORMALIZATION_FAILED_WARNING = "type_normalization_failed"
RECORDS_NOT_LIST_WARNING = "records_not_list"
TOP_LEVEL_NOT_OBJECT_WARNING = "top_level_not_object"


class CloudStructuredOutputError(RuntimeError):
    """Raised when cloud model output cannot be parsed as a safe JSON object."""


@dataclass
class CloudStructuredOutputReport:
    warnings: list[str] = field(default_factory=list)
    unknown_keys: list[str] = field(default_factory=list)
    type_normalization_failed: list[str] = field(default_factory=list)
    dropped_record_count: int = 0
    normalized_record_count: int = 0

    def add_warning(self, warning: str) -> None:
        if warning not in self.warnings:
            self.warnings.append(warning)

    def add_unknown_keys(self, keys: set[str]) -> None:
        if keys:
            self.add_warning(UNKNOWN_KEYS_WARNING)
        for key in sorted(keys):
            if key not in self.unknown_keys:
                self.unknown_keys.append(key)

    def add_type_normalization_failed(self, key: str) -> None:
        self.add_warning(TYPE_NORMALIZATION_FAILED_WARNING)
        if key not in self.type_normalization_failed:
            self.type_normalization_failed.append(key)


class TransientCloudAPIError(RuntimeError):
    """Raised only after retry-exhausted transient cloud/API/network failures."""

    def __init__(self, message: str = "", *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message or "Cloud API/network temporarily unavailable after retries.")


def is_transient_cloud_error(exc: BaseException) -> bool:
    return isinstance(exc, TransientCloudAPIError)


def transient_cloud_failure_summary(exc: BaseException) -> str:
    if isinstance(exc, TransientCloudAPIError) and exc.status_code is not None:
        return f"Transient cloud/API failure after retries (HTTP {exc.status_code})."
    return "Transient cloud/API/network failure after retries."


def tail_text(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def get_ollama_models(base_url: str) -> list[str]:
    url = base_url.rstrip("/") + "/api/tags"
    with urllib.request.urlopen(url, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    return [item.get("name", "") for item in payload.get("models", []) if item.get("name")]


def choose_model(requested_model: str, available_models: list[str]) -> str:
    if requested_model in available_models:
        return requested_model
    for model in [DEFAULT_MODEL, "qwen3.5:9b", "deepseek-r1:7b", "gemma4:e4b", "gpt-oss:20b"]:
        if model in available_models:
            return model
    if available_models:
        return available_models[0]
    raise RuntimeError("Ollama 没有可用模型，请先在 Ollama 中安装模型。")


def model_order(primary_model: str, available_models: list[str], auto_fallback: bool) -> list[str]:
    if not auto_fallback:
        return [primary_model]
    candidates = [primary_model, DEFAULT_MODEL, "qwen3.5:9b", "deepseek-r1:7b", "gemma4:e4b", "gpt-oss:20b"]
    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if item in available_models and item not in seen:
            out.append(item)
            seen.add(item)
    return out or [primary_model]


def pydantic_to_dict(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "dict"):
        return result.dict()
    if isinstance(result, dict):
        return result
    raise TypeError(f"无法转换 LLM 返回值：{type(result)!r}")


def message_content(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def parse_cloud_extraction_payload(content: Any) -> dict[str, Any]:
    try:
        raw = extract_json_object(message_content(content))
    except (json.JSONDecodeError, TypeError, ValueError):
        raise CloudStructuredOutputError(
            f"Cloud structured output validation failed: {MALFORMED_JSON_WARNING}."
        ) from None
    if not isinstance(raw, dict):
        raise CloudStructuredOutputError(
            f"Cloud structured output validation failed: {TOP_LEVEL_NOT_OBJECT_WARNING}."
        ) from None
    return raw


def raw_records(raw: dict[str, Any]) -> list[dict[str, Any]]:
    records = raw.get("records")
    if isinstance(records, list):
        return [item for item in records if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def blank_labeled_row(fields: list[dict[str, str]], key_to_label: dict[str, str]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for index, _item in enumerate(fields, start=1):
        key = f"field_{index:02d}"
        row[key_to_label[key]] = ""
    return row


def _expected_field_keys(fields: list[dict[str, str]]) -> set[str]:
    return {f"field_{index:02d}" for index, _item in enumerate(fields, start=1)}


def _records_with_report(
    raw: dict[str, Any], expected_keys: set[str],
) -> tuple[list[dict[str, Any]], CloudStructuredOutputReport]:
    report = CloudStructuredOutputReport()
    records = raw.get("records")
    if isinstance(records, list):
        raw_records_value = records
    elif "records" not in raw:
        if expected_keys and any(key in raw for key in expected_keys):
            report.add_warning(SINGLE_OBJECT_FALLBACK_WARNING)
            raw_records_value = [raw]
        else:
            report.add_warning(MISSING_RECORDS_WARNING)
            raw_records_value = []
    else:
        report.add_warning(RECORDS_NOT_LIST_WARNING)
        raw_records_value = []

    records_out: list[dict[str, Any]] = []
    for record in raw_records_value:
        if not isinstance(record, dict):
            report.add_warning(NON_OBJECT_RECORD_WARNING)
            report.dropped_record_count += 1
            continue
        if expected_keys:
            report.add_unknown_keys(set(record) - expected_keys)
        records_out.append(record)
    return records_out, report


def labeled_rows_with_report(
    raw: dict[str, Any], fields: list[dict[str, str]], key_to_label: dict[str, str],
) -> tuple[list[dict[str, Any]], CloudStructuredOutputReport]:
    from .quality import clean_extracted_value, normalize_cloud_value

    expected_keys = _expected_field_keys(fields)
    records, report = _records_with_report(raw, expected_keys)
    rows: list[dict[str, Any]] = []
    for record in records:
        row: dict[str, Any] = {}
        for index, item in enumerate(fields, start=1):
            key = f"field_{index:02d}"
            label = key_to_label[key]
            field_type = item.get("type", "str")
            raw_value = record.get(key)
            value = normalize_cloud_value(raw_value, field_type)
            if field_type in {"float", "int"} and raw_value is not None:
                if clean_extracted_value(raw_value) and value == "":
                    report.add_type_normalization_failed(key)
            row[label] = value
        rows.append(row)
    if not rows:
        rows = [blank_labeled_row(fields, key_to_label)]
    report.normalized_record_count = len(rows)
    return rows, report


def labeled_rows(
    raw: dict[str, Any], fields: list[dict[str, str]], key_to_label: dict[str, str],
) -> list[dict[str, Any]]:
    rows, _report = labeled_rows_with_report(raw, fields, key_to_label)
    return rows


def build_extraction_chain(
    model_name: str, base_url: str, num_ctx: int, llm_timeout: int,
    runtime: RuntimeDeps, extraction_model: Any,
):
    client_kwargs = {} if llm_timeout <= 0 else {"timeout": llm_timeout}
    llm = runtime.ChatOllama(
        model=model_name, temperature=0, num_ctx=num_ctx, num_predict=8192,
        keep_alive="30m", base_url=base_url, sync_client_kwargs=client_kwargs,
    )
    structured_llm = llm.with_structured_output(extraction_model)
    prompt = runtime.ChatPromptTemplate.from_messages([
        (
            "system",
            BIOLOGY_RULES
            + PROVENANCE_HINT_RULE,
        ),
        (
            "human",
            "文件名：{file_name}\n\n"
            "需要抽取的字段：\n{field_instructions}\n\n"
            "{quality_hint}\n\n"
            "PDF 转换文本如下，可能已截断：\n\n{markdown_text}",
        ),
    ])
    return prompt | structured_llm


def cloud_chat_completion(
    base_url: str, api_key: str, model: str,
    messages: list[dict[str, str]], llm_timeout: int,
    response_dir: Path | None = None,
    retry_count: int | None = None,
    on_retry: Any = None,
) -> str:
    base_url_error = validate_cloud_base_url_security(base_url)
    if base_url_error:
        raise RuntimeError(base_url_error)
    url = base_url.rstrip("/") + "/chat/completions"
    last_exc: BaseException | None = None
    attempts = CLOUD_RETRY_COUNT if retry_count is None else max(1, min(5, retry_count))
    for attempt in range(attempts):
        body = {
            "model": model, "messages": messages, "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        if model.startswith("doubao-seed-2-1-") or model == "doubao-seed-evolving":
            # The model console documents minimal as non-thinking mode. Keep
            # deterministic extraction bounded rather than spending the output
            # budget on hidden reasoning. Other providers retain their contract.
            body["reasoning_effort"] = os.getenv("ARK_REASONING_EFFORT", "minimal")
            body["max_tokens"] = 16000
        data = json_dumps_utf8(body).encode("utf-8")
        request = urllib.request.Request(
            url, data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json", "Accept": "application/json",
            },
            method="POST",
        )
        try:
            if llm_timeout and llm_timeout > 0:
                response_ctx = urllib.request.urlopen(request, timeout=llm_timeout, context=tls_context())
            else:
                response_ctx = urllib.request.urlopen(request, context=tls_context())
            with response_ctx as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            if response_dir is not None:
                response_dir = Path(response_dir)
                response_dir.mkdir(parents=True, exist_ok=True)
                # Only the model response is retained, never request headers or credentials.
                (response_dir / f"response-{time.time_ns()}.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            if payload["choices"][0].get("finish_reason") == "length":
                raise CloudStructuredOutputError("Model output was truncated; use a smaller extraction chunk.")
            return payload["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            last_exc = exc
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            if not retryable or attempt >= attempts - 1:
                if retryable:
                    raise TransientCloudAPIError(
                        f"Cloud API transient HTTP {exc.code} after retries.",
                        status_code=exc.code,
                    ) from exc
                error_code = ""
                try:
                    error_code = str(json.loads(exc.read()).get("error", {}).get("code", ""))
                except (ValueError, AttributeError, OSError, TypeError):
                    pass
                suffix = f" ({error_code})" if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", error_code) else ""
                raise RuntimeError(f"Cloud API HTTP {exc.code}{suffix}. Check cloud API configuration or request settings.") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise RuntimeError("HTTPS 证书校验失败；请检查虚拟环境的 CA 证书路径或 SSL_CERT_FILE 配置。") from exc
            last_exc = exc
            if attempt >= attempts - 1:
                raise TransientCloudAPIError(
                    "云端连接超时或网络不可用，自动重试后仍失败；已完成的分段已缓存，可重试继续。"
                ) from exc
        except (json.JSONDecodeError, KeyError) as exc:
            raise RuntimeError(f"Cloud API returned malformed response: {redact_sensitive_text(short_error(exc))}") from exc
        delay = min(CLOUD_RETRY_MAX_DELAY_SECONDS, CLOUD_RETRY_BASE_DELAY_SECONDS * (2**attempt))
        if on_retry:
            on_retry(f"云端暂未返回有效响应，{delay:g} 秒后重试（第 {attempt+2}/{attempts} 次请求）")
        time.sleep(delay)
    raise TransientCloudAPIError("Cloud API/network temporarily unavailable after retries.") from last_exc


def test_openai_compatible_chat(base_url: str, api_key: str, model: str, timeout: float = 10.0) -> dict[str, Any]:
    base_url_error = validate_cloud_base_url_security(base_url)
    if base_url_error:
        raise RuntimeError(base_url_error)
    if not str(api_key or "").strip():
        raise RuntimeError("LLM API KEY is empty.")
    if not str(model or "").strip():
        raise RuntimeError("LLM model is empty.")

    body = {
        "model": str(model).strip(),
        "messages": [
            {"role": "system", "content": "Return only a compact JSON object."},
            {"role": "user", "content": 'Return exactly {"ok": true, "status": "ok"}.'},
        ],
        "temperature": 0,
        "max_tokens": 40,
        "response_format": {"type": "json_object"},
    }
    if model.startswith("doubao-seed-2-1-") or model == "doubao-seed-evolving":
        body["reasoning_effort"] = os.getenv("ARK_REASONING_EFFORT", "minimal")
    request = urllib.request.Request(
        str(base_url).strip().rstrip("/") + "/chat/completions",
        data=json_dumps_utf8(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=tls_context()) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        content = payload["choices"][0]["message"]["content"]
        parsed = extract_json_object(message_content(content))
        if parsed.get("ok") is True or str(parsed.get("status") or "").strip().lower() in {"ok", "success"}:
            return parsed
        raise ValueError("Test response JSON did not include ok/status.")
    except urllib.error.HTTPError as exc:
        body_text = ""
        try:
            body_text = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"Cloud API HTTP {exc.code}: {redact_sensitive_text(tail_text(body_text))}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise RuntimeError(f"Cloud API test failed: {redact_sensitive_text(short_error(exc))}") from exc


def translate_item_batch_to_chinese_cloud(
    base_url: str, api_key: str, model: str,
    items: list[dict[str, str]], llm_timeout: int,
) -> dict[str, str]:
    from .quality import parse_translation_payload
    if not items:
        return {}
    messages = [
        {
            "role": "system",
            "content": (
                "你是化工文献数据清洗助手。请把用户给出的 JSON 数组中每个 text 翻译成简洁、准确的中文。"
                "只翻译自然语言和英文术语，保留化学式、CAS 号、数字、单位、百分号、型号和牌号。"
                "催化剂、反应器、物性方法、反应热、反应机理等术语要用化工领域常用中文。"
                "不要解释，不要补充原文没有的信息。"
                "只输出合法 JSON 对象，格式为 {\"items\":[{\"id\":\"...\",\"translation\":\"...\"}]}。"
            ),
        },
        {"role": "user", "content": json.dumps(items, ensure_ascii=False)},
    ]
    content = cloud_chat_completion(base_url, api_key, model, messages, llm_timeout)
    return parse_translation_payload(extract_json_object(content))


MODEL_DISCOVERY_ERROR = "Failed to fetch models. Please check Base URL, API key, or enter the model manually."


def build_openai_compatible_models_url(base_url: str) -> str:
    cleaned = str(base_url or "").strip()
    if not cleaned:
        raise RuntimeError("LLM BASE URL is empty.")
    return cleaned.rstrip("/") + "/models"


def parse_openai_compatible_model_ids(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError("Invalid model list response: missing data list.")
    models: list[str] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Invalid model list response: model item is not an object.")
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            raise ValueError("Invalid model list response: model id is missing.")
        if model_id not in seen:
            models.append(model_id)
            seen.add(model_id)
    if not models:
        raise ValueError("No models were returned by the provider.")
    return models


def fetch_openai_compatible_models(base_url: str, api_key: str, timeout: float = 10.0) -> list[str]:
    if not str(base_url or "").strip():
        raise RuntimeError("LLM BASE URL is empty.")
    if not str(api_key or "").strip():
        raise RuntimeError("LLM API KEY is empty.")
    base_url_error = validate_cloud_base_url_security(base_url)
    if base_url_error:
        raise RuntimeError(base_url_error)
    url = build_openai_compatible_models_url(base_url)
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=tls_context()) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        return parse_openai_compatible_model_ids(payload)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(MODEL_DISCOVERY_ERROR) from exc


def extract_with_cloud_api(
    pdf_path: Path, config: dict[str, Any], fields: list[dict[str, str]],
    key_to_label: dict[str, str], markdown_text: str, quality_hint: str = "",
) -> list[dict[str, Any]]:
    api_key = str(config.get("cloud_api_key") or "").strip()
    base_url = str(config.get("cloud_base_url") or "").strip()
    model = str(config.get("cloud_model") or config.get("model") or "").strip()
    if not api_key:
        raise RuntimeError("云端 API KEY 为空。请在页面填写 LLM API KEY。")
    if not base_url:
        raise RuntimeError("云端 BASE URL 为空。")
    if not model:
        raise RuntimeError("云端模型名称为空。")
    schema_lines = []
    for index, item in enumerate(fields, start=1):
        schema_lines.append(
            f'- "field_{index:02d}": {item["label"]} [{requirement_label(item.get("requirement", "optional"))}]，'
            f'{item["description"]}，{requirement_rule(item.get("requirement", "optional"))}，{missing_rule(item["type"])}'
        )
    messages = [
        {
            "role": "system",
            "content": (
                BIOLOGY_RULES
                + "只输出合法 JSON 对象，顶层必须为 records 数组，字段 key 使用 field_01 等指定编号。"
                + PROVENANCE_HINT_RULE
            ),
        },
        {
            "role": "user",
            "content": (
                f"文件名：{pdf_path.name}\n\n"
                "请按下面 JSON key 抽取字段：\n"
                + "\n".join(schema_lines)
                + (f"\n\n二次核查要求：\n{quality_hint}\n" if quality_hint else "")
                + "\n\nPDF 转换文本如下，可能已截断：\n\n"
                + markdown_text
            ),
        },
    ]
    args = (base_url, api_key, model, messages, int(config.get("llm_timeout") or 0))
    kwargs = {}
    if config.get("response_dir"):
        kwargs.update(response_dir=Path(config["response_dir"]), retry_count=config.get("cloud_retry_count"))
    if config.get("log"):
        kwargs["on_retry"] = config["log"]
    content = cloud_chat_completion(*args, **kwargs)
    raw = parse_cloud_extraction_payload(content)
    return labeled_rows(raw, fields, key_to_label)
