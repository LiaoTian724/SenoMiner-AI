"""Paper inputs via local documents or the vendored PubMed skill."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .pdf import read_pdf_as_markdown_with_mode
from .science_skills import SkillError


def normalize_identifier(value: str) -> str:
    """Only literature identifiers, never arbitrary URLs or local paths."""
    identifier = str(value or "").strip()
    if re.fullmatch(r"(?:PMID:)?\s*\d{1,10}", identifier, re.I):
        return "PMID:" + re.sub(r"\D", "", identifier)
    if re.fullmatch(r"(?:PMC:)?\s*PMC\d{1,10}", identifier, re.I):
        return re.search(r"PMC\d+", identifier, re.I).group().upper()
    doi = re.sub(r"^(?:doi:\s*|https?://(?:dx\.)?doi.org/)", "", identifier, flags=re.I)
    if len(doi) <= 250 and re.fullmatch(r"10\.\d{4,9}/[^\s\"\[\]<>]+", doi):
        return "DOI:" + doi
    raise ValueError("请输入有效的 DOI、PMID 或 PMC 编号；其他文献请上传 PDF。")


def resolve_pubmed_identifier(value: str, skills: Any) -> str:
    identifier = normalize_identifier(value)
    if identifier.startswith("PMID:"):
        return identifier[5:]
    if identifier.startswith("PMC"):
        ids = skills.call("pubmed", "find_linked_biological_data", identifier[3:], "pubmed", "pmc_pubmed", "--dbfrom", "pmc")
    else:
        ids = skills.call("pubmed", "search_pubmed", f'"{identifier[4:]}"[AID]', "--max_results", "2")
    ids = [str(v) for v in ids if re.fullmatch(r"\d{1,10}", str(v))]
    if len(ids) != 1:
        raise ValueError("No unique PubMed record matches this identifier；未找到唯一对应文献，请上传 PDF。")
    return ids[0]


def load_paper(value: str, skills: Any, runtime: Any, pdf_mode: str = "pymupdf4llm") -> dict:
    path = Path(value).expanduser()
    if path.is_file():
        if path.suffix.lower() == ".pdf":
            text, parser = read_pdf_as_markdown_with_mode(path, pdf_mode, runtime)
        elif path.suffix.lower() in {".txt", ".md"}:
            text, parser = path.read_text(encoding="utf-8"), "text"
        else:
            raise ValueError("Supported files: PDF, UTF-8 TXT, Markdown")
        if not text.strip():
            raise ValueError("No extractable text; provide OCR text for scanned PDFs")
        return {"source": path.name, "text": text, "scope": "local_document", "parser": parser}
    pmid = resolve_pubmed_identifier(value, skills)
    papers = skills.call("pubmed", "fetch_article_abstracts", pmid)
    if not papers or not papers[0].get("title"):
        raise ValueError("PubMed record has no article metadata")
    paper = papers[0]
    text = ""
    scope = "abstract_only"
    try:
        full = skills.call("pubmed", "get_full_text_pmc", pmid)
        text = full.get("full_text", "")
        if text.strip():
            scope = "oa_full_text"
    except SkillError:
        pass
    if not text.strip():
        text = paper.get("abstract") or ""
    if not text.strip():
        raise ValueError("No accessible full text or abstract; supply the PDF")
    return {"source": f"PMID:{pmid}", "pmid": pmid, "doi": paper.get("doi") or "",
            "title": paper["title"], "pubdate":paper.get("pubdate") or "", "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "text": text, "scope": scope, "parser": "science_skills_pubmed"}
