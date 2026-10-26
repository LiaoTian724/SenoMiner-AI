"""Build a compound-first catalog from primary-paper extraction reports."""
from __future__ import annotations

import json
import re
import urllib.request
import hashlib
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .science_skills import ScienceSkills
from .evidence_story import attach_evidence_stories
from .claim_review import load_review
from .structures import molecular_structure
from .evidence_cards import load_cards, card_groups

DEMO_SOURCE = "PMC6796530-Hickson-2019.pdf"
DEMO_META = {
    "title": "Senolytics decrease senescent cells in humans: Preliminary report from a clinical trial of Dasatinib plus Quercetin in individuals with diabetic kidney disease",
    "pmid": "31542391", "pmcid": "PMC6796530",
    "doi": "10.1016/j.ebiom.2019.08.069",
}


def _object(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _name(name: str, names_in_paper: set[str]) -> str:
    """Only expand the local D+Q abbreviation when this paper defines it."""
    cleaned = re.sub(r"\s+", " ", name).strip()
    has_definition = any("dasatinib" in n.casefold() and "quercetin" in n.casefold()
                         and re.search(r"\bD\s*\+\s*Q\b", n, re.I) for n in names_in_paper)
    if has_definition and (re.search(r"\bD\s*\+\s*Q\b", cleaned, re.I)
                           or ("dasatinib" in cleaned.casefold() and "quercetin" in cleaned.casefold())):
        return "Dasatinib + Quercetin"
    if cleaned.casefold() == "fisetin":
        return "Fisetin"
    return re.sub(r"\s*\([^)]{1,40}\)$", "", cleaned).strip() or cleaned


def _components(row: dict) -> list[dict]:
    external = _object(row.get("external_evidence"))
    parts = []
    raw_parts = external.get("components", [])
    for part in raw_parts if isinstance(raw_parts, list) else []:
        if not isinstance(part, dict):
            continue
        pubchem = _object(part.get("pubchem"))
        chembl = _object(part.get("chembl"))
        props = _object(pubchem.get("properties"))
        cid = str(pubchem.get("cid") or "")
        parts.append({
            "name": str(part.get("query_name") or ""),
            "cid": cid if cid.isdigit() else "",
            "chembl_id": str(chembl.get("id") or ""),
            "formula": str(props.get("MolecularFormula") or ""),
            "mass": str(props.get("MolecularWeight") or ""),
            "iupac_name": str(props.get("IUPACName") or ""),
            "inchikey": str(pubchem.get("inchikey") or ""),
            "synonyms": pubchem.get("synonyms", [])[:8],
            "literature": _object(part.get("literature")).get("papers", [])[:5],
        })
    return parts


def _identity(row: dict, name: str) -> dict:
    external = _object(row.get("external_evidence"))
    pubchem = _object(external.get("pubchem"))
    chembl = _object(external.get("chembl"))
    props = _object(pubchem.get("properties"))
    cid = str(row.get("pubchem_cid") or pubchem.get("cid") or "")
    if not cid.isdigit():
        cid = ""
    return {
        "name": name, "cid": cid, "chembl_id": str(row.get("chembl_id") or chembl.get("id") or ""),
        "formula": str(props.get("MolecularFormula") or ""),
        "mass": str(props.get("MolecularWeight") or ""),
        "iupac_name": str(props.get("IUPACName") or ""),
        "inchikey": str(pubchem.get("inchikey") or ""),
        "synonyms": pubchem.get("synonyms", [])[:8],
        "literature": _object(external.get("literature")).get("papers", [])[:5],
        "components": _components(row),
    }


def _identity_key(identity: dict, label: str) -> str:
    parts = identity.get("components") or []
    if len(parts) >= 2 and all(p.get("cid") for p in parts):
        return "combination:" + "+".join(sorted(p["cid"] for p in parts))
    if not parts and identity.get("cid"):
        return "cid:" + identity["cid"]
    return label.casefold()


def _paper_meta(report: dict, rows: list[dict], folder: Path) -> dict:
    source = _object(report.get("source"))
    source_name = str(source.get("source") or folder.name)
    if source_name == DEMO_SOURCE:
        meta = DEMO_META.copy()
    else:
        meta = {
            "title": str(source.get("title") or next((r.get("paper_title") for r in rows if r.get("paper_title")), source_name)),
            "pmid": str(source.get("pmid") or next((r.get("pmid") for r in rows if r.get("pmid")), "")),
            "pmcid": str(source.get("pmcid") or ""),
            "doi": str(source.get("doi") or next((r.get("doi") for r in rows if r.get("doi")), "")),
        }
    meta.update({"id": str(report.get("source_sha256") or folder.name)[:20],
                 "source_name": source_name, "scope": str(source.get("scope") or ""),
                 "url": str(source.get("url") or (f'https://pubmed.ncbi.nlm.nih.gov/{meta["pmid"]}/' if meta["pmid"].isdigit() else ""))})
    return meta


def _read_time(report: dict, path: Path) -> float:
    """New reports store ingestion time; legacy reports use their completion mtime."""
    try:
        return datetime.fromisoformat(str(report.get("read_at") or "").replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return path.stat().st_mtime


def build_catalog(root: Path = PROJECT_ROOT) -> dict:
    """Read every completed report; never equate cited studies with the source paper."""
    compounds: dict[str, dict] = {}
    papers: list[dict] = []
    source_text_by_paper: dict[str, str] = {}
    report_paths = sorted((root / "output").glob("**/report.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:200]
    for path in report_paths:
        if path.stat().st_size > 30_000_000:
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            read_time = _read_time(report, path)
            reviewed_path = path.parent / "report.revalidated.json"
            if reviewed_path.is_file() and reviewed_path.stat().st_size <= 30_000_000:
                try:
                    reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    reviewed = {}
                if (reviewed.get("derived_from") == "report.json"
                        and reviewed.get("source_sha256") == report.get("source_sha256")
                        and reviewed.get("source") == report.get("source")):
                    report = reviewed
            rows = [r for r in report.get("records", []) if isinstance(r, dict)]
            source_text = (path.parent / "source.md").read_text(encoding="utf-8")
        except (OSError, ValueError, TypeError):
            continue
        paper = _paper_meta(report, rows, path.parent)
        paper.update({"read_timestamp": read_time, "read_at": datetime.fromtimestamp(read_time, timezone.utc).isoformat()})
        review = load_review(path.parent, rows, source_text)
        cards = load_cards(path.parent, rows, source_text, review) if review else None
        paper["review_status"] = "complete" if review else "pending"
        paper["card_status"] = "complete" if cards is not None else "pending"
        paper["review_decisions"] = [{k: d.get(k) for k in ("input_name", "canonical_name", "verdict", "role", "scope", "reason")}
                                     for d in review.get("decisions", [])]
        source_text_by_paper[paper["id"]] = source_text
        if paper["scope"] == "abstract_only":
            papers.append({**paper, "candidate_records": len(rows), "catalog_records": 0})
            continue
        paper_count = 0
        decisions = {d["canonical_name"]: d for d in review.get("decisions", []) if d.get("verdict") == "accepted"}
        for card in cards or []:
            decision = decisions.get(card["name"])
            if not decision:
                continue
            label = _name(card["name"], {card["name"]})
            if not label:
                continue
            identity = _identity({}, label)
            reviewed_identity = review.get("identities", {}).get(decision["canonical_name"], {})
            if (isinstance(reviewed_identity, dict) and reviewed_identity.get("query_name") == decision["canonical_name"]
                    and reviewed_identity.get("status") in {"resolved", "combination_components_resolved"}):
                identity = _identity({"external_evidence": reviewed_identity}, label)
            key = _identity_key(identity, label)
            item = compounds.setdefault(key, {"id": key, "name": label, "status": "paper_experiment",
                                              "identity": identity, "papers": []})
            if not item["identity"]["components"] and identity["components"]:
                item["identity"] = identity
            elif not item["identity"]["cid"] and identity["cid"]:
                item["identity"] = identity
            entry = next((p for p in item["papers"] if p["id"] == paper["id"]), None)
            if entry is None:
                entry = {**paper, "cards": [], "claim_review": {k: decision.get(k) for k in
                         ("scope", "role", "reason", "evidence_quote", "evidence_location")}}
                item["papers"].append(entry)
            entry["cards"].append(card)
            paper_count += len(card["outcomes"])
        papers.append({**paper, "candidate_records": len(rows), "catalog_records": paper_count})
    for item in compounds.values():
        for paper in item["papers"]:
            paper["groups"] = card_groups(paper.pop("cards"), paper['pmid'])
            paper["experiment_groups"] = len(paper["groups"])
            paper["outcomes"] = sum(len(g["outcomes"]) for g in paper["groups"])
            attach_evidence_stories(paper, item["name"], source_text_by_paper.get(paper["id"], ""))
        item["papers"].sort(key=lambda p: -p["read_timestamp"])
        item["latest_read_timestamp"] = item["papers"][0]["read_timestamp"]
    # Stable ties preserve each article's extraction order rather than alphabetising drugs.
    items = sorted(compounds.values(), key=lambda c: -c["latest_read_timestamp"])
    papers.sort(key=lambda p: -p["read_timestamp"])
    processed_sources = {p["source_name"] for p in papers}
    local_pdfs = [{"name": p.name, "processed": p.name in processed_sources}
                  for p in sorted((root / "input_pdfs").glob("*.pdf")) if p.is_file()][:100]
    return {"compounds": items, "papers": papers, "local_pdfs": local_pdfs,
            "summary": {"compounds": len(items), "papers": len(papers),
                        "direct": sum(c["status"] == "paper_experiment" for c in items),
                        "experiment_groups": sum(p["experiment_groups"] for c in items for p in c["papers"]),
                        "outcomes": sum(p["outcomes"] for c in items for p in c["papers"])}}


def local_pdf_output(name: str, root: Path = PROJECT_ROOT) -> Path:
    if Path(name).name != name or not name.lower().endswith(".pdf") or len(name) > 180:
        raise ValueError("无效 PDF 文件名")
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:14]
    return root / "output" / "papers" / f"local-{digest}"


def search_pubmed(query: str, root: Path = PROJECT_ROOT, limit: int = 8) -> list[dict]:
    clean = re.sub(r"[\x00-\x1f\[\]{}\"']", " ", str(query or ""))[:120].strip()
    if len(clean) < 3:
        raise ValueError("请输入至少 3 个字符的检索词")
    skills = ScienceSkills(root / "output" / ".search_cache")
    ids = skills.call("pubmed", "search_pubmed",
                      f'({clean}) AND (senolytic OR senescence OR aging) NOT Review[pt]',
                      "--max_results", str(limit))
    ids = [str(x) for x in ids if str(x).isdigit()][:limit]
    if not ids:
        return []
    raw = skills.call("pubmed", "fetch_article_abstracts", ",".join(ids))
    return [{"pmid": str(x.get("pmid") or ""), "title": str(x.get("title") or ""),
             "doi": str(x.get("doi") or ""), "abstract": str(x.get("abstract") or "")[:700],
             "url": f'https://pubmed.ncbi.nlm.nih.gov/{x.get("pmid")}/'}
            for x in raw if isinstance(x, dict) and str(x.get("pmid") or "").isdigit()]


@lru_cache(maxsize=64)
def pubchem_structure(cid: str) -> str:
    return molecular_structure(cid, PROJECT_ROOT)["sdf"]


def structure_details(cid: str) -> dict:
    return molecular_structure(cid, PROJECT_ROOT)
