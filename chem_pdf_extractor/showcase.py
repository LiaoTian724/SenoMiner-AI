"""A single-paper, read-only presentation of the biomedical extraction output."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, RuntimeDeps
from .security import redact_sensitive_text


PDF_NAME = "PMC6796530-Hickson-2019.pdf"
PAPER_TITLE = (
    "Senolytics decrease senescent cells in humans: Preliminary report from a "
    "clinical trial of Dasatinib plus Quercetin in individuals with diabetic kidney disease"
)
PMID = "31542391"
PMCID = "PMC6796530"
DOI = "10.1016/j.ebiom.2019.08.069"
RESULT_DIR = "单篇演示"


def paper_path(root: Path = PROJECT_ROOT) -> Path:
    return root / "input_pdfs" / PDF_NAME


def result_path(root: Path = PROJECT_ROOT) -> Path:
    return root / "output" / RESULT_DIR


def downloadable_file(kind: str, root: Path = PROJECT_ROOT) -> tuple[Path, str, str] | None:
    files = {
        "pdf": (paper_path(root), "application/pdf", PDF_NAME),
        "excel": (result_path(root) / "experiments.xlsx",
                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "experiments.xlsx"),
        "json": (result_path(root) / "report.json", "application/json", "report.json"),
        "source": (result_path(root) / "source.md", "text/markdown; charset=utf-8", "source.md"),
    }
    return files.get(kind)


def _json_object(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def snapshot(root: Path = PROJECT_ROOT) -> dict:
    """Return only presentation fields; no credentials or arbitrary local paths."""
    output = result_path(root)
    pdf = paper_path(root)
    report_file = output / "report.json"
    ready = report_file.is_file() and (output / "experiments.xlsx").is_file()
    payload: dict[str, Any] = {
        "ready": ready,
        "paper": {
            "title": PAPER_TITLE, "pmid": PMID, "pmcid": PMCID, "doi": DOI,
            "pdf_name": PDF_NAME, "pdf_available": pdf.is_file(),
            "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{PMID}/",
        },
        "progress": {
            "pdf_ready": pdf.is_file(),
            "text_ready": (output / "source.md").is_file(),
            "chunks_done": len(list((output / "extraction_cache").glob("*.json")))
            if (output / "extraction_cache").is_dir() else 0,
            "report_ready": ready,
        },
        "summary": {}, "records": [],
    }
    if not ready:
        return payload
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload["ready"] = False
        payload["progress"]["report_ready"] = False
        return payload
    records = report.get("records", [])
    if not isinstance(records, list):
        records = []
    presented = []
    cids: set[str] = set()
    literature: set[str] = set()
    for row in records:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("pubchem_cid") or "").strip()
        if cid.isdigit():
            cids.add(cid)
        literature.update(x for x in str(row.get("related_pmids") or "").split("; ") if x.isdigit())
        external = _json_object(row.get("external_evidence"))
        components = []
        for component in external.get("components", []) if isinstance(external.get("components"), list) else []:
            if not isinstance(component, dict):
                continue
            components.append({
                "name": str(component.get("query_name") or ""),
                "status": str(component.get("status") or ""),
                "pubchem_cid": _json_object(component.get("pubchem")).get("cid", ""),
                "chembl_id": _json_object(component.get("chembl")).get("id", ""),
            })
            component_cid = str(components[-1]["pubchem_cid"] or "")
            if component_cid.isdigit():
                cids.add(component_cid)
        presented.append({
            key: row.get(key, "") for key in (
                "compound_name", "compound_role", "record_type", "experiment_model",
                "model_type", "treatment_dose", "treatment_duration", "administration_route",
                "control_group", "sample_size", "assay_method", "measured_endpoint",
                "observed_result", "reported_effect", "effect_size", "statistical_evidence",
                "source_location", "evidence_origin", "enrichment_status", "pubchem_cid",
                "chembl_id", "related_pmids", "needs_review", "evidence_status",
                "missing_fields", "experiment_id", "source_document",
            )
        } | {
            "field_evidence": _json_object(row.get("field_evidence")),
            "evidence_checks": _json_object(row.get("evidence_checks")),
            "procedure_steps": _json_list(row.get("procedure_steps")),
            "components": components,
        })
    payload["records"] = presented
    payload["summary"] = {
        "records": len(presented),
        "chemical_candidates": sum(r.get("record_type") == "chemical_candidate"
                                   and r.get("compound_role") == "tested" for r in presented),
        "compounds": len({str(r.get("compound_name") or "").strip().casefold()
                          for r in presented if r.get("record_type") == "chemical_candidate"
                          and r.get("compound_role") == "tested"
                          and str(r.get("compound_name") or "").strip()}),
        "needs_review": sum(bool(r.get("needs_review")) for r in presented),
        "literal_support": sum(r.get("evidence_status") == "text_supported" for r in presented),
        "pubchem_cids": len(cids),
        "related_pmids": len(literature),
        "model": report.get("llm", {}).get("model", ""),
    }
    return payload


def render_page(token: str) -> str:
    html = (Path(__file__).resolve().parent / "templates" / "showcase.html").read_text(encoding="utf-8")
    return html.replace("__LOCAL_TOKEN__", json.dumps(token))


def run_demo(runtime: RuntimeDeps, log) -> None:
    """Run the existing biomedical pipeline for the fixed local PDF only."""
    from .biomedical import extract_article
    from .science_skills import ScienceSkills
    from .sources import load_paper

    pdf = paper_path()
    if not pdf.is_file():
        raise FileNotFoundError("演示论文 PDF 不存在，请查看 input_pdfs。")
    model = os.getenv("CHEM_PDF_EXTRACTOR_MODEL") or os.getenv("ARK_MODEL_ID") or ""
    base_url = os.getenv("CHEM_PDF_EXTRACTOR_BASE_URL") or os.getenv("ARK_BASE_URL") or ""
    api_key = os.getenv("CHEM_PDF_EXTRACTOR_API_KEY") or os.getenv("ARK_API_KEY") or ""
    if not all((model, base_url, api_key)):
        raise RuntimeError("云端模型配置不完整，请检查根目录 .env。")
    output = result_path()
    skills = ScienceSkills(output / "database_cache")
    log("解析论文 PDF")
    paper = load_paper(str(pdf), skills, runtime, "pymupdf4llm")
    log(f"完成 PDF 解析，共 {len(paper['text'])} 字符；开始分段提取")
    config = {
        "llm_provider": "cloud", "cloud_api_key": api_key,
        "cloud_base_url": base_url, "cloud_model": model, "model": model,
        "llm_timeout": 240, "chunk_size": 8000, "workers": 3,
        "enrich_databases": True, "literature_limit": 3, "log": log,
    }
    rows = extract_article(paper, [], config, runtime, skills, output)
    log(f"已导出 {len(rows)} 条记录；请逐条核验原文和实验对应关系")


def safe_error(error: Exception) -> str:
    return redact_sensitive_text(str(error))
