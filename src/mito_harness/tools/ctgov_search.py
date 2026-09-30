"""ClinicalTrials.gov search via API v2."""

from __future__ import annotations

from typing import Any

from mito_harness.cache import DiskCache
from mito_harness.schemas import SourceKind, UnifiedRecord
from mito_harness.tools.http import SourceClient
from setting import get_settings


async def ctgov_search(terms: str, from_year: int, to_year: int, max_results: int = 10) -> list[UnifiedRecord]:
    """Search ClinicalTrials.gov interventional studies started within the window."""
    s = get_settings()
    src = s.sources.ctgov
    client = SourceClient(
        "ctgov",
        src.base_url,
        DiskCache(s.paths.cache_dir),
        src.timeout_seconds,
        src.retries,
        src.retry_backoff_seconds,
        rate_limit_seconds=src.rate_limit_seconds,
    )

    params: dict[str, Any] = {
        "query.term": terms,
        "filter.advanced": f"AREA[StartDate]RANGE[{from_year}-01-01,MAX]",
        "pageSize": max_results,
        "countTotal": "true",
    }
    payload: dict[str, Any] = await client.get_json(client.base_url, params)
    return parse_ctgov(payload)


def parse_ctgov(payload: dict[str, Any]) -> list[UnifiedRecord]:
    """Parse ClinicalTrials.gov v2 response into UnifiedRecords (pure function)."""
    records: list[UnifiedRecord] = []
    for study in payload.get("studies", []):
        protocol = study.get("protocolSection", {})
        id_mod = protocol.get("identificationModule", {})
        status_mod = protocol.get("statusModule", {})
        design = protocol.get("designModule", {})
        desc = protocol.get("descriptionModule", {})

        nct_id = id_mod.get("nctId", "")
        title = id_mod.get("briefTitle", "") or id_mod.get("officialTitle", "")
        if not (nct_id and title):
            continue

        phases = design.get("phases") or []
        phase = "/".join(phases) if phases else None
        try:
            enrollment = int(design.get("enrollmentInfo", {}).get("count") or 0) or None
        except (TypeError, ValueError):
            enrollment = None

        start = str(status_mod.get("startDateStruct", {}).get("date") or "")
        year = int(start[:4]) if start[:4].isdigit() else None

        brief = desc.get("briefSummary", "")
        records.append(
            UnifiedRecord(
                source=SourceKind.ctgov,
                title=title,
                abstract=brief or None,
                year=year,
                nct_id=nct_id,
                trial_phase=phase,
                enrollment=enrollment,
            )
        )
    return records
