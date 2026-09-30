"""parse_record: strict Pydantic validation/normalization of extracted study data.

The DataExtractor agent emits raw dicts; this atomic tool validates them into
``StudyRecord`` (anti-hallucination gate: fields that do not fit the schema
fail loudly instead of being silently coerced).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from mito_harness.schemas import Direction, EvidenceLevel, SourceKind, StudyPhase, StudyRecord

_PHASE_ALIASES: dict[str, StudyPhase] = {
    "preclinical": StudyPhase.preclinical,
    "in vitro": StudyPhase.preclinical,
    "animal": StudyPhase.preclinical,
    "early phase 1": StudyPhase.early_phase1,
    "early_phase1": StudyPhase.early_phase1,
    "phase 1": StudyPhase.phase1,
    "phase1": StudyPhase.phase1,
    "phase i": StudyPhase.phase1,
    "phase 1/phase 2": StudyPhase.phase1,
    "phase 2": StudyPhase.phase2,
    "phase2": StudyPhase.phase2,
    "phase ii": StudyPhase.phase2,
    "phase 2/phase 3": StudyPhase.phase2,
    "phase 3": StudyPhase.phase3,
    "phase3": StudyPhase.phase3,
    "phase iii": StudyPhase.phase3,
    "phase 4": StudyPhase.phase4,
    "phase4": StudyPhase.phase4,
    "phase iv": StudyPhase.phase4,
    "n/a": StudyPhase.not_applicable,
    "na": StudyPhase.not_applicable,
    "not applicable": StudyPhase.not_applicable,
    "observational": StudyPhase.not_applicable,
}

_DESIGN_EVIDENCE: list[tuple[str, EvidenceLevel]] = [
    (r"meta-?analy|systematic review", EvidenceLevel.meta),
    (r"randomi[sz]ed|rct|double-?blind|placebo-?controlled", EvidenceLevel.rct),
    (r"observational|cohort|case-?control|registry|cross-?sectional|case series", EvidenceLevel.observational),
    (r"preclinical|animal|in vitro|mouse|mice|rat model", EvidenceLevel.preclinical),
]


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().lower() if value else ""


def _normalize_phase(raw: Any) -> StudyPhase:
    key = _norm_text(raw)
    if key in _PHASE_ALIASES:
        return _PHASE_ALIASES[key]
    match = re.search(r"phase\s*([1-4])", key)
    if match:
        return StudyPhase(f"phase{match.group(1)}")
    if not key:
        return StudyPhase.not_applicable
    raise ValueError(f"unrecognized phase: {raw!r}")


def _normalize_evidence(raw: Any, design: str) -> EvidenceLevel:
    key = _norm_text(raw)
    for level in EvidenceLevel:
        if level.value in key:
            return level
    design_lc = _norm_text(design)
    for pattern, level in _DESIGN_EVIDENCE:
        if re.search(pattern, design_lc):
            return level
    raise ValueError(f"cannot infer evidence level from {raw!r} / design {design!r}")


def _normalize_direction(raw: Any) -> Direction:
    key = _norm_text(raw)
    aliases = {
        "positive": Direction.positive,
        "benefit": Direction.positive,
        "improvement": Direction.positive,
        "improved": Direction.positive,
        "negative": Direction.negative,
        "worsening": Direction.negative,
        "harm": Direction.negative,
        "worse": Direction.negative,
        "neutral": Direction.neutral,
        "no effect": Direction.neutral,
        "no difference": Direction.neutral,
        "null": Direction.neutral,
        "unclear": Direction.unclear,
        "mixed": Direction.unclear,
        "ambiguous": Direction.unclear,
    }
    if key in aliases:
        return aliases[key]
    for token, direction in aliases.items():
        if token in key:
            return direction
    raise ValueError(f"unrecognized direction: {raw!r}")


def _normalize_ref_id(raw: Any) -> str:
    ref = str(raw).strip().upper()
    if re.fullmatch(r"\d{6,9}", ref):
        return ref
    if re.fullmatch(r"NCT\d{8}", ref):
        return ref
    if ref.startswith("10."):
        return str(raw).strip()
    raise ValueError(f"ref_id must be a PMID, NCT id or DOI: {raw!r}")


def parse_record(raw: dict[str, Any]) -> StudyRecord:
    """Validate + normalize a raw extraction dict into a strict StudyRecord."""
    normalized: dict[str, Any] = dict(raw)
    normalized["ref_id"] = _normalize_ref_id(raw["ref_id"])
    normalized["phase"] = _normalize_phase(raw.get("phase"))
    normalized["evidence_level"] = _normalize_evidence(raw.get("evidence_level"), raw.get("design", ""))
    if raw.get("source") not in {kind.value for kind in SourceKind}:
        raise ValueError(f"unknown source: {raw.get('source')!r}")
    for outcome in normalized.get("outcomes", []):
        outcome["direction"] = _normalize_direction(outcome.get("direction"))
    try:
        return StudyRecord.model_validate(normalized)
    except ValidationError as exc:
        raise ValueError(f"record failed schema validation: {exc.error_count()} errors") from exc
