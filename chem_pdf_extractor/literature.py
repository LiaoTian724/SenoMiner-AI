"""Bounded PubMed searches through the Science Skills wrapper."""
from __future__ import annotations

import re
from typing import Any

AGING_TERMS = "(senescence[Title/Abstract] OR aging[Title/Abstract] OR lifespan[Title/Abstract] OR senolytic[Title/Abstract])"


def build_pubmed_query(name: str, synonyms: list[str] | None = None) -> str:
    terms = []
    for value in [name, *(synonyms or [])[:3]]:
        # Quotes and square brackets from source text must not become query operators.
        cleaned = re.sub(r'["\[\]{}\n\r]', " ", str(value)).strip()
        if 2 <= len(cleaned) <= 100 and cleaned.casefold() not in {t.casefold() for t in terms}:
            terms.append(cleaned)
    if not terms:
        raise ValueError("No searchable compound name")
    names = " OR ".join(f'"{term}"[Title/Abstract]' for term in terms)
    return f"({names}) AND {AGING_TERMS}"


def search_related_papers(skills: Any, name: str, synonyms: list[str] | None = None,
                          source_pmid: str = "", limit: int = 5) -> dict:
    limit = max(1, min(20, int(limit)))
    query = build_pubmed_query(name, synonyms)
    ids = skills.call("pubmed", "search_pubmed", query, "--max_results", str(limit + 1))
    if not isinstance(ids, list):
        raise ValueError("Unexpected PubMed search response")
    ids = [str(pmid) for pmid in ids if str(pmid).isdigit() and str(pmid) != str(source_pmid)][:limit]
    papers = skills.call("pubmed", "fetch_article_abstracts", ",".join(ids)) if ids else []
    if not isinstance(papers, list):
        raise ValueError("Unexpected PubMed abstract response")
    for paper in papers:
        paper["url"] = f'https://pubmed.ncbi.nlm.nih.gov/{paper["pmid"]}/'
        paper["evidence_scope"] = "external abstract; not independently extracted experimental evidence"
    return {"status": "ok" if papers else "no_results", "query": query, "papers": papers}
