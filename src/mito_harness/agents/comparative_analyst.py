"""ComparativeAnalystAgent: mito-therapy vs standard-of-care comparison matrix.

Methodology (PLAN.md section 7): direction-only synthesis, never a cross-study
average. One plot marker per study x outcome; arms labeled mito/standard.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from mito_harness.schemas import ComparisonResult
from mito_harness.skills_loader import SkillCapability, inject_skills

ANALYST_INSTRUCTIONS = """\
You are the comparative analyst of a mitochondrial-medicine research harness.

You receive structured StudyRecords (already extracted from real abstracts) plus
the configured standard-of-care per disease. Build the comparison of
mitochondria-targeted therapy versus standard treatment.

Hard methodological rules:
1. One plot item = one study/arm/outcome. NEVER average effects across studies.
2. direction encodes ONLY the sign of the effect for that arm on that outcome;
   significant=true only when p<0.05 was reported.
3. arm='mito' for the mitochondria-targeted intervention records; arm='standard'
   for records where is_standard_of_care=true or the comparator arm of the same
   trial (if reported). If no standard-arm data exists for an outcome, emit only
   the mito marker - do not invent the standard side.
4. study_label format: "<short trial/drug name> (<phase>)", e.g. "RESCUE (Ph3)".
   ref_id = the record's PMID/NCT, always.
5. evidence: copy the record's evidence_level (see the evidence_levels skill).
6. gap_cells: aggregate per (intervention x disease): n_studies, top_evidence
   (highest tier found), refs list.
7. insights: 3-6 bullet strings, each ending with the supporting ref_id(s).
   State honestly where evidence is negative or absent.
"""


def build_comparison_agent(model: Any, skills: list[SkillCapability] | None = None) -> Agent[Any, ComparisonResult]:
    return Agent(
        model,
        output_type=ComparisonResult,
        instructions=inject_skills(ANALYST_INSTRUCTIONS, list(skills or [])),
    )


def comparison_prompt(studies_json: str, standards_json: str) -> str:
    return (
        "Build the mito-therapy vs standard-of-care comparison from the extracted records below.\n\n"
        f"--- STANDARD-OF-CARE MAP ---\n{standards_json}\n\n"
        f"--- EXTRACTED STUDY RECORDS (JSON) ---\n{studies_json}\n"
    )
