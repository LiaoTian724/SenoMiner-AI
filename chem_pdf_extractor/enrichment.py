"""Identity-conservative PubChem → ChEMBL → PubMed knowledge enrichment."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .literature import search_related_papers
from .science_skills import ScienceSkills, SkillError


def _first_property(data: Any, cid: int) -> dict:
    if not isinstance(data, dict):
        return {}
    rows = data.get("PropertyTable", {}).get("Properties", [])
    return next((r for r in rows if r.get("CID") == cid), {})


def enrich_compound(name: str, skills: Any, *, source_pmid: str = "",
                    expected_inchikey: str = "", literature_limit: int = 5) -> dict:
    result: dict[str, Any] = {
        "query_name": name, "status": "unresolved", "pubchem": {}, "chembl": {},
        "literature": {}, "errors": [], "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
    expanded = re.sub(r"\s*\([^)]*[+&][^)]*\)\s*$", "", name)
    parts = [part.strip() for part in re.split(r"\s+(?:and|plus|with)\s+|\s*\+\s*", expanded, flags=re.I)]
    if 2 <= len(parts) <= 3 and all(len(part) >= 3 for part in parts):
        components = [enrich_compound(part, skills, source_pmid=source_pmid,
                                      literature_limit=literature_limit) for part in parts]
        result["status"] = "combination_components_resolved" if all(c["status"] == "resolved" for c in components) else "combination_unresolved"
        result["components"] = components
        result["identity_basis"] = "explicit component names in combination label; no single-compound identity assigned"
        result["interpretation"] = "Component database facts do not attribute the combination's experimental effect to either component alone."
        papers = {}
        for component in components:
            for paper in component.get("literature", {}).get("papers", []):
                papers[str(paper["pmid"])] = paper
        result["literature"] = {"status": "component_searches", "papers": list(papers.values())}
        return result
    # Paper-local identifiers and mixtures must not be guessed into single molecules.
    if (re.fullmatch(r"(?:compound|cmpd|molecule|sample)\s*[-#]?\s*[A-Za-z0-9]+", name, re.I)
            or re.search(r"\s(?:and|plus|with)\s|\+|;", name, re.I)
            or name.strip().lower() in {"", "n/a", "unknown", "none", "vehicle"}):
        result["reason"] = "local identifier, mixture or non-specific name; requires manual identity resolution"
        return result
    try:
        resolved = skills.call("pubchem", "resolve", "--name", name)
        ids = resolved.get("identifiers", {}).get("IdentifierList", {}).get("CID", []) if not resolved.get("error") else []
        result["pubchem"]["candidate_cids"] = ids
        if len(ids) != 1:
            result["status"] = "ambiguous" if ids else "unresolved"
            return result
        cid = ids[0]
        structure = _first_property(resolved.get("properties"), cid)
        inchikey = structure.get("InChIKey", "")
        if not inchikey:
            result["reason"] = "PubChem structure response missing InChIKey"
            return result
        if expected_inchikey and expected_inchikey != inchikey:
            result["status"] = "identity_conflict"
            return result
        result["status"] = "resolved"
        result["identity_basis"] = "unique PubChem name result; verify against paper structure when available"
        result["pubchem"].update({"cid": cid, "inchikey": inchikey, "structure": structure,
                                    "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"})
    except (SkillError, ValueError, KeyError, TypeError, AttributeError):
        result["status"] = "error"
        result["errors"].append("pubchem_resolution_failed")
        return result
    synonyms: list[str] = []
    for command in ("properties", "synonyms"):
        try:
            data = skills.call("pubchem", command, "--cid", str(cid))
            if command == "properties":
                result["pubchem"]["properties"] = _first_property(data, cid)
            else:
                entries = data.get("InformationList", {}).get("Information", [])
                synonyms = next((x.get("Synonym", []) for x in entries if x.get("CID") == cid), [])
                result["pubchem"]["synonyms"] = synonyms[:20]
        except (SkillError, ValueError, TypeError, AttributeError):
            result["errors"].append(f"pubchem_{command}_failed")
    try:
        data = skills.call("chembl", "molecule", "--filter",
                           f"molecule_structures__standard_inchi_key={inchikey}", "--limit", "5")
        molecules = [m for m in data.get("molecules", [])
                     if (m.get("molecule_structures") or {}).get("standard_inchi_key") == inchikey]
        if len(molecules) == 1:
            chembl_id = molecules[0]["molecule_chembl_id"]
            result["chembl"] = {"status": "resolved", "id": chembl_id, "identity_basis": "exact full InChIKey",
                                 "url": f"https://www.ebi.ac.uk/chembl/explore/compound/{chembl_id}"}
            for endpoint, key in (("activity", "activities"), ("mechanism", "mechanisms")):
                try:
                    payload = skills.call("chembl", endpoint, "--filter", f"molecule_chembl_id={chembl_id}", "--limit", "10")
                    result["chembl"][key] = payload.get(key, [])
                except (SkillError, ValueError, TypeError, AttributeError):
                    result["errors"].append(f"chembl_{endpoint}_failed")
        else:
            result["chembl"] = {"status": "ambiguous" if molecules else "unresolved"}
    except (SkillError, ValueError, KeyError, TypeError, AttributeError):
        result["chembl"] = {"status": "error"}
        result["errors"].append("chembl_resolution_failed")
    try:
        result["literature"] = search_related_papers(skills, name, synonyms, source_pmid, literature_limit)
    except (SkillError, ValueError, KeyError, TypeError, AttributeError):
        result["literature"] = {"status": "error", "papers": []}
        result["errors"].append("pubmed_search_failed")
    return result


def enrich_rows(rows: list[dict], cache_dir: Path, *, enabled: bool = True,
                literature_limit: int = 5, skills: Any = None, log=None, approved: dict | None = None) -> list[dict]:
    """Never overwrite extraction fields with external facts; retain one row per experiment."""
    client = skills or (ScienceSkills(cache_dir) if enabled else None)
    compounds = {}
    out = []
    alias_definitions: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        label = str(row.get("compound_name") or "").strip()
        match = re.fullmatch(r"(.+?)\s*\(([^()]{2,24})\)", label)
        if (match and row.get("source_id") and _compound_name_is_supported(row)
                and re.search(r"\s(?:plus|and|with)\s|\+", match[1], re.I) and "+" in match[2]):
            key = (str(row["source_id"]), re.sub(r"\s+", "", match[2]).casefold())
            alias_definitions.setdefault(key, set()).add(label)
    for row in rows:
        item = dict(row)
        name = str(item.get("compound_name") or "").strip()
        candidates = alias_definitions.get((str(row.get("source_id") or ""), re.sub(r"\s+", "", name).casefold()), set())
        query_name = next(iter(candidates)) if len(candidates) == 1 else name
        decision = approved.get(str(row.get("experiment_id") or "")) if approved is not None else None
        if decision:
            query_name = decision["canonical_name"]
        if query_name != name:
            item["compound_identity_label"] = query_name
            item["compound_identity_basis"] = "explicit grounded alias definition in the same source"
        identity = (query_name.casefold(), str(row.get("pmid") or ""), str(row.get("inchikey") or ""))
        if not enabled:
            item["enrichment_status"] = "disabled"
        elif approved is not None and not decision:
            item["enrichment_status"] = "skipped_claim_review"
        elif item.get("record_type") == "nonchemical_intervention":
            item["enrichment_status"] = "skipped_nonchemical_intervention"
        elif item.get("record_type") == "background_mention":
            item["enrichment_status"] = "skipped_background_mention"
        elif (not decision and item.get("evidence_status") != "text_supported"
              and not _compound_name_is_supported(item)):
            item["enrichment_status"] = "skipped_unverified_experiment"
        else:
            if identity not in compounds:
                if log:
                    log(f"数据库增强：{name}")
                compounds[identity] = enrich_compound(query_name, client, source_pmid=identity[1],
                                                     expected_inchikey=identity[2], literature_limit=literature_limit)
            enrichment = compounds[identity]
            item["external_evidence"] = json.dumps(enrichment, ensure_ascii=False)
            item["enrichment_status"] = enrichment["status"]
            item["pubchem_cid"] = enrichment["pubchem"].get("cid", "")
            item["chembl_id"] = enrichment["chembl"].get("id", "")
            item["related_pmids"] = "; ".join(str(p["pmid"]) for p in enrichment.get("literature", {}).get("papers", []))
        out.append(item)
    return out


def _compound_name_is_supported(row: dict) -> bool:
    """Identity lookup requires a grounded name, not verified biological efficacy."""
    try:
        checks = json.loads(row.get("evidence_checks") or "{}")
        return checks.get("compound_name", {}).get("status") == "text_supported"
    except (TypeError, ValueError, AttributeError):
        return False
