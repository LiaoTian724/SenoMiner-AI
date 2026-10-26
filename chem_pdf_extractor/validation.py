"""Deterministic source checks. Text matches are review aids, not efficacy proofs."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

KEY_FIELDS = ("compound_name", "experiment_model", "treatment_dose",
              "treatment_duration", "assay_method", "observed_result")
NUMBERED_EVIDENCE_KEYS = {"compound_name": "field_01", "experiment_model": "field_06",
                          "treatment_dose": "field_09", "treatment_duration": "field_12",
                          "assay_method": "field_16", "observed_result": "field_19"}
EMPTY = {"", "n/a", "null", "none", "unreported", "not reported", "未报告"}


def normalized(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def source_span(source: str, quote: str) -> dict[str, Any] | None:
    """Exact, case-sensitive source span, permitting whitespace changes only."""
    quote = normalized(quote)
    if not quote:
        return None
    pattern = r"\s+".join(re.escape(part) for part in quote.split(" "))
    match = re.search(pattern, source)
    if not match:
        return None
    markers = list(re.finditer(r"(?:<!--\s*Page\s+(\d+)\s*-->|^#{1,6}\s*Page\s+(\d+)\s*$)",
                               source[:match.start()], re.I | re.M))
    page = next((int(v) for v in markers[-1].groups() if v), None) if markers else None
    return {"start": match.start(), "end": match.end(), "page": page,
            "text": source[match.start():match.end()]}


def _json_value(value: Any, expected: type, default: Any) -> Any:
    if isinstance(value, expected):
        return value
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, expected) else default
    except (TypeError, ValueError):
        return default


def validate_experiment(row: dict[str, Any], source: str, source_id: str) -> dict[str, Any]:
    out = dict(row)
    name = str(row.get("compound_name") or "")
    nonchemical = bool(re.search(
        r"\b(?:preadipocytes|fibroblasts|senescent cells?|knockout|transplantation|"
        r"X[- ]ray irradiation|untreated control|no senolytics?)\b|^\d+\s*Gy\b",
        name, re.I,
    ))
    if nonchemical:
        out["record_type"] = "nonchemical_intervention"
    elif str(row.get("evidence_origin") or "").strip().casefold() == "background":
        out["record_type"] = "background_mention"
    else:
        out["record_type"] = "chemical_candidate"
    quotes = _json_value(row.get("field_evidence"), dict, {})
    checks: dict[str, Any] = {}
    missing = []
    for field in KEY_FIELDS:
        value = normalized(row.get(field))
        if value.lower() in EMPTY:
            missing.append(field)
            checks[field] = {"status": "not_reported"}
            continue
        quote = quotes.get(field) or quotes.get(NUMBERED_EVIDENCE_KEYS[field], "")
        span = source_span(source, quote) if isinstance(quote, str) else None
        # A true quote with a fabricated value must not pass the check.
        supported = bool(span and value in normalized(span["text"]))
        if field == "compound_name" and span and "+" in value and not supported:
            parts = [part.strip().casefold() for part in value.split("+")]
            quotation = normalized(span["text"]).casefold()
            supported = len(parts) in (2, 3) and all(part and part in quotation for part in parts)
        checks[field] = {"status": "text_supported" if supported else "needs_review", "span": span}
    steps = _json_value(row.get("experimental_procedure"), list, [])
    checked_steps = []
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            continue
        span = source_span(source, step.get("evidence_text", ""))
        action = normalized(step.get("action"))
        supported = bool(action and span and action in normalized(span["text"]))
        checked_steps.append({"step": i, "action": action, "evidence": span,
                              "status": "text_supported" if supported else "needs_review"})
    required_supported = all(checks[f]["status"] == "text_supported"
                             for f in ("compound_name", "experiment_model", "observed_result"))
    review = (not required_supported or any(c["status"] == "needs_review" for c in checks.values())
              or any(s["status"] == "needs_review" for s in checked_steps)
              or bool(row.get("experimental_procedure") and not checked_steps))
    out["evidence_checks"] = json.dumps(checks, ensure_ascii=False)
    out["procedure_steps"] = json.dumps(checked_steps, ensure_ascii=False)
    out["missing_fields"] = "; ".join(missing)
    out["evidence_status"] = "needs_review" if review else "text_supported"
    out["needs_review"] = review
    # Clinical effectiveness and cross-experiment linkage are never inferred by string matching.
    out["validation_scope"] = "literal text support only; experiment linkage and effect interpretation require review"
    out["source_id"] = source_id
    identity = [source_id] + [normalized(row.get(f)) for f in KEY_FIELDS]
    out["experiment_id"] = "exp-" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:16]
    return out
