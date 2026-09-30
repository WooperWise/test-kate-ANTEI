"""Europe PMC search via the public REST API."""

from __future__ import annotations

from typing import Any

from mito_harness.cache import DiskCache
from mito_harness.schemas import SourceKind, UnifiedRecord
from mito_harness.tools.http import SourceClient
from setting import get_settings


async def europepmc_search(terms: str, from_year: int, to_year: int, max_results: int = 10) -> list[UnifiedRecord]:
    """Search Europe PMC and return normalized records."""
    s = get_settings()
    src = s.sources.europepmc
    client = SourceClient(
        "europepmc",
        src.base_url,
        DiskCache(s.paths.cache_dir),
        src.timeout_seconds,
        src.retries,
        src.retry_backoff_seconds,
        rate_limit_seconds=src.rate_limit_seconds,
    )

    query = f"({terms}) AND (PUB_YEAR:[{from_year} TO {to_year}])"
    params: dict[str, Any] = {
        "query": query,
        "format": src.format,
        "resultType": src.result_type,
        "pageSize": max_results,
    }
    payload: dict[str, Any] = await client.get_json(f"{client.base_url}/{src.search}", params)
    return parse_europepmc(payload)


def parse_europepmc(payload: dict[str, Any]) -> list[UnifiedRecord]:
    """Parse Europe PMC search response into UnifiedRecords (pure function)."""
    records: list[UnifiedRecord] = []
    for res in payload.get("resultList", {}).get("result", []):
        title = res.get("title", "")
        if not title:
            continue
        pub_types = res.get("pubTypeList", {}).get("pubType", [])
        if isinstance(pub_types, list):
            pubtypes = [p.get("name", "") if isinstance(p, dict) else str(p) for p in pub_types]
        else:
            pubtypes = [str(pub_types)]
        year_raw = res.get("pubYear")
        try:
            year = int(year_raw) if year_raw else None
        except (TypeError, ValueError):
            year = None
        records.append(
            UnifiedRecord(
                source=SourceKind.europepmc,
                title=title,
                abstract=res.get("abstractText") or None,
                journal=res.get("journalTitle"),
                year=year,
                pmid=str(res.get("pmid")) if res.get("pmid") else None,
                doi=res.get("doi"),
                pubtypes=[p for p in pubtypes if p],
            )
        )
    return records
