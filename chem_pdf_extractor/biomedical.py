"""Article + supplements → experiments → evidence checks → database report."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .biology import ANTI_AGING_FIELDS, BIOLOGY_RULES
from .config import append_review_aid_fields, build_dynamic_model, import_runtime_dependencies
from .enrichment import enrich_rows
from .export import export_excel, write_jsonl
from .llm import CloudStructuredOutputError, TransientCloudAPIError, build_extraction_chain, extract_with_cloud_api, labeled_rows, pydantic_to_dict
from .science_skills import ScienceSkills
from .sources import load_paper
from .validation import validate_experiment
from .claim_review import review_rows, approved_records, populate_identities
from .evidence_cards import extract_cards


def text_chunks(text: str, size: int = 18000, overlap: int = 1200):
    """Bound context size, retain overlap and inspect every source character."""
    if not 0 <= overlap < size:
        raise ValueError("overlap must be smaller than chunk size")
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        yield text[start:end]
        if end == len(text):
            break
        start = end - overlap


def extract_article(paper: dict, supplements: list[dict], config: dict,
                    runtime: Any, skills: Any, output_dir: Path) -> list[dict]:
    documents = [paper, *supplements]
    source = "\n\n".join(f'# Document: {d["source"]}\n{d["text"]}' for d in documents)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_id = hashlib.sha256(source.encode()).hexdigest()
    # Offsets in the report address this exact retained text, before any normalization.
    (output_dir / "source.md").write_text(source, encoding="utf-8")
    fields = append_review_aid_fields(ANTI_AGING_FIELDS)
    model, mapping = build_dynamic_model(fields, runtime)
    chain = None
    if config.get("llm_provider") == "ollama":
        chain = build_extraction_chain(config["model"], config.get("ollama_base_url", "http://127.0.0.1:11434"),
                                       32768, config.get("llm_timeout", 120), runtime, model)
    rows = []
    chunks = list(text_chunks(source, config.get("chunk_size", 8000)))
    log = config.get("log")
    checkpoint_dir = output_dir / "extraction_cache"
    checkpoint_dir.mkdir(exist_ok=True)
    def call_cloud_chunk(chunk):
        try:
            return extract_with_cloud_api(Path(paper["source"]),
                {**config, "response_dir": str(output_dir / "model_responses"), "cloud_retry_count": 1}, fields, mapping, chunk)
        except (CloudStructuredOutputError, TransientCloudAPIError):
            if len(chunk) <= 2500:
                raise
            if log:
                log(f"Splitting {len(chunk)}-character chunk after failed, invalid or truncated output")
            middle = len(chunk) // 2
            return call_cloud_chunk(chunk[:middle+200]) + call_cloud_chunk(chunk[middle-200:])
    def extract_one_chunk(pair):
        chunk_index, chunk = pair
        if log:
            log(f"Extracting chunk {chunk_index}/{len(chunks)} ({len(chunk)} characters)")
        checkpoint_key = hashlib.sha256(json.dumps({
            "text": chunk, "fields": fields, "rules": BIOLOGY_RULES,
            "provider": config.get("llm_provider", "cloud"),
            "model": config.get("cloud_model") or config.get("model"),
            "base_url": config.get("cloud_base_url"),
        }, sort_keys=True).encode()).hexdigest()
        checkpoint = checkpoint_dir / f"{checkpoint_key}.json"
        records = None
        if checkpoint.exists():
            try:
                saved = json.loads(checkpoint.read_text(encoding="utf-8"))
                if isinstance(saved, list) and all(isinstance(row, dict) for row in saved):
                    records = saved
                    if log:
                        log(f"Reused cached extraction chunk {chunk_index}")
            except (OSError, ValueError):
                pass
        if records is None and chain is None:
            records = call_cloud_chunk(chunk)
        elif records is None:
            from .config import field_instructions
            raw = chain.invoke({"file_name": paper["source"], "field_instructions": field_instructions(fields),
                                "markdown_text": chunk, "quality_hint": ""})
            records = labeled_rows(pydantic_to_dict(raw), fields, mapping)
        fd, pending_name = tempfile.mkstemp(dir=checkpoint_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False)
        Path(pending_name).replace(checkpoint)
        if log:
            log(f"Chunk {chunk_index}: {len(records)} candidate experiment records")
        return records

    workers = 1 if chain is not None else max(1, min(4, int(config.get("workers", 3))))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for records in executor.map(extract_one_chunk, enumerate(chunks, 1)):
            for record in records:
                if not str(record.get("compound_name") or "").strip():
                    continue
                row = validate_experiment(record, source, source_id)
                # Only metadata resolved by PubMed can override model-provided identifiers.
                if paper.get("pmid"):
                    row["pmid"] = paper["pmid"]
                row["source_scope"] = paper["scope"]
                row["source_document"] = paper["source"]
                row["source_url"] = paper.get("url", "")
                rows.append(row)
    unique = {}
    for row in rows:
        old = unique.get(row["experiment_id"])
        if old is None or old["needs_review"] and not row["needs_review"]:
            unique[row["experiment_id"]] = row
    rows = list(unique.values())
    review = review_rows(rows, source, config, output_dir)
    extract_cards(rows, source, review, config, output_dir)
    rows = enrich_rows(rows, output_dir / "database_cache", skills=skills,
                       enabled=config.get("enrich_databases", True),
                       literature_limit=config.get("literature_limit", 5), log=log, approved=approved_records(review))
    if config.get("enrich_databases", True):
        populate_identities(review, rows, output_dir, skills)
    write_jsonl(output_dir / "experiments.jsonl", rows)
    (output_dir / "report.json").write_text(json.dumps({
        "source": {k: v for k, v in paper.items() if k != "text"},
        "supplements": [{k: v for k, v in d.items() if k != "text"} for d in supplements],
        "source_sha256": source_id, "records": rows,
        "read_at": datetime.now(timezone.utc).isoformat(),
        "llm": {"provider": config.get("llm_provider", "cloud"),
                "model": config.get("cloud_model") or config.get("model") or "",
                "chunk_size": config.get("chunk_size", 8000), "workers": workers},
        "interpretation": "Reported effects in the source model; text matches do not establish clinical efficacy or correct experiment linkage.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    export_excel(rows, output_dir / "experiments.xlsx", runtime)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="PDF/TXT/MD path, PMID:123, PMC123, or DOI:10.x/y")
    parser.add_argument("--supplement", action="append", default=[], help="Supplement file for the SAME paper; repeatable")
    parser.add_argument("--output", type=Path, default=Path("output/biomedical"))
    parser.add_argument("--llm-provider", choices=["cloud", "ollama"], default="cloud")
    parser.add_argument("--model", default="")
    parser.add_argument("--pdf-mode", default="pymupdf4llm")
    parser.add_argument("--no-enrichment", action="store_true")
    parser.add_argument("--literature-limit", type=int, default=5)
    parser.add_argument("--related-fulltexts", type=int, default=0, help="Also extract up to N related papers (0-5, one hop)")
    parser.add_argument("--chunk-size", type=int, default=8000, help="Characters per extraction chunk (minimum 2000)")
    parser.add_argument("--workers", type=int, default=3, help="Cloud request workers (1-4); Ollama always uses one")
    parser.add_argument("--llm-timeout", type=int, default=240, help="Per-request timeout in seconds")
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    config = {"llm_provider": args.llm_provider, "cloud_api_key": os.getenv("CHEM_PDF_EXTRACTOR_API_KEY") or os.getenv("ARK_API_KEY", ""),
              "cloud_base_url": os.getenv("CHEM_PDF_EXTRACTOR_BASE_URL") or os.getenv("ARK_BASE_URL", ""),
              "cloud_model": args.model or os.getenv("CHEM_PDF_EXTRACTOR_MODEL") or os.getenv("ARK_MODEL_ID", ""),
              "model": args.model or os.getenv("ARK_MODEL_ID", ""), "llm_timeout": max(30, args.llm_timeout),
              "chunk_size": max(2000, args.chunk_size), "workers": max(1, min(4, args.workers)),
              "enrich_databases": not args.no_enrichment, "literature_limit": max(1, min(20, args.literature_limit)),
              "log": lambda message: print(message, flush=True)}
    if args.llm_provider == "cloud" and not all(config[k] for k in ("cloud_api_key", "cloud_base_url", "cloud_model")):
        parser.error("Configure cloud credentials in .env or use Ollama")
    if args.llm_provider == "ollama" and not args.model:
        parser.error("Ollama requires --model")
    runtime = import_runtime_dependencies()
    skills = ScienceSkills(args.output / "database_cache")
    paper = load_paper(args.input, skills, runtime, args.pdf_mode)
    supplements = [load_paper(s, skills, runtime, args.pdf_mode) for s in args.supplement]
    rows = extract_article(paper, supplements, config, runtime, skills, args.output)
    print(f"Extracted {len(rows)} experiment records ({paper['scope']}); report: {args.output / 'report.json'}")
    # One bounded expansion, never recursive crawling or positive-result voting.
    related = {}
    for row in rows:
        evidence = json.loads(row.get("external_evidence") or "{}")
        for p in evidence.get("literature", {}).get("papers", []):
            related[str(p["pmid"])] = p
    for pmid in list(related)[:max(0, min(5, args.related_fulltexts))]:
        related_paper = load_paper(f"PMID:{pmid}", skills, runtime, args.pdf_mode)
        related_config = {**config, "enrich_databases": False}
        extract_article(related_paper, [], related_config, runtime, skills, args.output / "related" / pmid)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        from .security import redact_sensitive_text
        raise SystemExit(f"Extraction failed: {redact_sensitive_text(str(exc))}") from None
