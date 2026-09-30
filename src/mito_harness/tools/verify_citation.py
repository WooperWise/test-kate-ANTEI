"""verify_citation: re-fetch PMID / NCT / DOI and cross-check the claim.

Anti-hallucination gate for the ReviewerValidator agent: an identifier is
"verified" only if it exists in the live (or cached) source registry AND the
fetched title is similar enough to the claimed one.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Any

from mito_harness.cache import DiskCache
from mito_harness.schemas import VerifyResult
from mito_harness.tools.http import SourceClient
from setting import get_settings

logger = logging.getLogger(__name__)

TITLE_SIMILARITY_THRESHOLD = 0.75


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), (b or "").lower().strip()).ratio()


async def _fetch_pubmed(pmid: str) -> dict[str, Any] | None:
    s = get_settings()
    src = s.sources.pubmed
    client = SourceClient(
        "pubmed",
        src.base_url,
        DiskCache(s.paths.cache_dir),
        src.timeout_seconds,
        src.retries,
        src.retry_backoff_seconds,
        rate_limit_seconds=src.rate_limit_seconds,
    )
    params: dict[str, Any] = {"db": "pubmed", "id": pmid, "retmode": "json"}
    if s.ncbi_api_key:
        params["api_key"] = s.ncbi_api_key
    payload = await client.get_json(f"{client.base_url}/esummary.fcgi", params)
    result = payload.get("result", {})
    return result.get(pmid) if isinstance(result, dict) else None


async def _fetch_ctgov(nct_id: str) -> dict[str, Any] | None:
    s = get_settings()
    src = s.sources.ctgov
    client = SourceClient(
        "ctgov",
        src.base_url.rsplit("/studies", 1)[0],
        DiskCache(s.paths.cache_dir),
        src.timeout_seconds,
        src.retries,
        src.retry_backoff_seconds,
        rate_limit_seconds=src.rate_limit_seconds,
    )
    return await client.get_json(
        f"{client.base_url}/studies/{nct_id}",
        {"fields": "protocolSection.identificationModule,protocolSection.statusModule"},
    )


async def _fetch_crossref(doi: str) -> dict[str, Any] | None:
    s = get_settings()
    client = SourceClient(
        "crossref",
        "https://api.crossref.org/works",
        DiskCache(s.paths.cache_dir),
        s.sources.pubmed.timeout_seconds,
        3,
        1.5,
        rate_limit_seconds=0.4,
    )
    payload = await client.get_json(f"{client.base_url}/{doi}", {})
    return payload.get("message")


def _year_from_date(date_struct: Any) -> int | None:
    if isinstance(date_struct, dict):
        raw = str(date_struct.get("date") or "")
        if raw[:4].isdigit():
            return int(raw[:4])
    return None


async def verify_citation(identifier: str, claimed_title: str, year_claimed: int | None = None) -> VerifyResult:
    """Re-fetch the identifier and verify title (and year if provided).

    Never raises: an unreachable/unparseable identifier degrades to verified=False
    so the reviewer can flag the claim instead of crashing the run.
    """
    ref = identifier.strip().upper()
    fetched_title: str | None = None
    year_fetched: int | None = None
    reason = ""

    try:
        if ref.startswith("NCT"):
            study = await _fetch_ctgov(ref)
            if study:
                ident = study.get("protocolSection", {}).get("identificationModule", {})
                fetched_title = ident.get("briefTitle") or ident.get("officialTitle")
                year_fetched = _year_from_date(
                    study.get("protocolSection", {}).get("statusModule", {}).get("startDateStruct")
                )
            else:
                reason = "NCT id not found on ClinicalTrials.gov"
        elif ref.isdigit():
            summary = await _fetch_pubmed(ref)
            if summary and not summary.get("error"):
                fetched_title = summary.get("title")
                pubdate = str(summary.get("pubdate") or "")
                year_fetched = int(pubdate[:4]) if pubdate[:4].isdigit() else None
            else:
                reason = "PMID not found in PubMed"
        elif ref.startswith("10."):
            message = await _fetch_crossref(identifier.strip())
            if message:
                titles = message.get("title") or []
                fetched_title = titles[0] if titles else None
                parts = message.get("issued", {}).get("date-parts", [[]])
                if parts and parts[0] and isinstance(parts[0][0], int):
                    year_fetched = parts[0][0]
            else:
                reason = "DOI not found on Crossref"
        else:
            reason = "identifier must be PMID, NCT id or DOI"
    except Exception as exc:  # noqa: BLE001 - degrade, never crash the review loop
        logger.warning("verify_citation fetch failed for %r: %s", identifier, exc)
        reason = f"fetch failed: {str(exc)[:120]}"

    similarity = _similarity(claimed_title, fetched_title or "")
    verified = bool(
        fetched_title
        and similarity >= TITLE_SIMILARITY_THRESHOLD
        and (year_claimed is None or year_fetched is None or abs(year_claimed - year_fetched) <= 1)
    )
    if fetched_title and similarity < TITLE_SIMILARITY_THRESHOLD:
        reason = reason or f"title mismatch (similarity={similarity:.2f})"
    elif fetched_title and year_claimed and year_fetched and abs(year_claimed - year_fetched) > 1:
        reason = reason or f"year mismatch (claimed {year_claimed}, fetched {year_fetched})"

    return VerifyResult(
        identifier=identifier,
        claimed_title=claimed_title,
        fetched_title=fetched_title,
        verified=verified,
        title_similarity=round(similarity, 3),
        year_claimed=year_claimed,
        year_fetched=year_fetched,
        reason=reason or ("ok" if verified else "not verified"),
    )
