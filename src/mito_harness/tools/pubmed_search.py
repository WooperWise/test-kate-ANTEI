"""PubMed search via NCBI E-utilities (esearch + efetch)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from mito_harness.cache import DiskCache
from mito_harness.schemas import SourceKind, UnifiedRecord
from mito_harness.tools.http import SourceClient
from setting import get_settings


def _client() -> SourceClient:
    s = get_settings()
    src = s.sources.pubmed
    return SourceClient(
        "pubmed",
        src.base_url,
        DiskCache(s.paths.cache_dir),
        src.timeout_seconds,
        src.retries,
        src.retry_backoff_seconds,
        rate_limit_seconds=src.rate_limit_seconds,
    )


async def pubmed_search(terms: str, from_year: int, to_year: int, max_results: int = 10) -> list[UnifiedRecord]:
    """Search PubMed and return normalized records (title+abstract+metadata)."""
    s = get_settings()
    src = s.sources.pubmed
    client = _client()

    params: dict[str, Any] = {
        "db": src.db,
        "term": terms,
        "retmode": src.retmode,
        "retmax": max_results,
        "sort": "date",
        "mindate": from_year,
        "maxdate": to_year,
        "datetype": "pdat",
    }
    if s.ncbi_api_key:
        params["api_key"] = s.ncbi_api_key

    esearch: dict[str, Any] = await client.get_json(f"{client.base_url}/{src.search}", params)
    idlist: list[str] = esearch.get("esearchresult", {}).get("idlist", [])
    if not idlist:
        return []

    fetch_params: dict[str, Any] = {"db": src.db, "id": ",".join(idlist), "retmode": "xml"}
    if s.ncbi_api_key:
        fetch_params["api_key"] = s.ncbi_api_key
    xml_text = await client.get_text(f"{client.base_url}/{src.fetch}", fetch_params)
    return parse_pubmed_xml(xml_text)


def parse_pubmed_xml(xml_text: str) -> list[UnifiedRecord]:
    """Parse PubMed efetch XML into UnifiedRecords (pure function, unit-testable)."""
    records: list[UnifiedRecord] = []
    root = ET.fromstring(xml_text)
    for article in root.iter("PubmedArticle"):
        medline = article.find("MedlineCitation")
        art = medline.find("Article") if medline is not None else None
        if art is None or medline is None:
            continue

        title_el = art.find("ArticleTitle")
        title = "".join(title_el.itertext()) if title_el is not None and title_el.text else ""

        abstract_parts: list[str] = []
        abstract_el = art.find("Abstract")
        if abstract_el is not None:
            for txt in abstract_el.iter("AbstractText"):
                label = txt.get("Label")
                chunk = "".join(txt.itertext()).strip()
                abstract_parts.append(f"{label}: {chunk}" if label else chunk)
        abstract = " ".join(abstract_parts) or None

        journal = None
        year = None
        journal_el = art.find("Journal")
        if journal_el is not None:
            journal_title = journal_el.find("ISOAbbreviation") or journal_el.find("Title")
            journal = journal_title.text if journal_title is not None else None
            year_el = journal_el.find("./JournalIssue/PubDate/Year")
            if year_el is not None and year_el.text:
                year = int(year_el.text)

        pmid_el = medline.find("PMID")
        pmid = pmid_el.text if pmid_el is not None else None

        pubtypes = [pt.text for pt in art.iter("PublicationType") if pt.text]

        doi = None
        for aid in article.iter("ArticleId"):
            if aid.get("IdType") == "doi":
                doi = aid.text

        if title:
            records.append(
                UnifiedRecord(
                    source=SourceKind.pubmed,
                    title=title,
                    abstract=abstract,
                    journal=journal,
                    year=year,
                    pmid=pmid,
                    doi=doi,
                    pubtypes=pubtypes,
                )
            )
    return records
