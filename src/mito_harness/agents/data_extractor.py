"""DataExtractorAgent: structured extraction from one fetched abstract/registration.

Anti-hallucination: the abstract text is the only source; the agent must pass its
draft through the parse_record tool (strict Pydantic gate) before returning.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, ModelRetry

from mito_harness.schemas import StudyRecord, UnifiedRecord
from mito_harness.skills_loader import SkillCapability, inject_skills
from mito_harness.tools.parse_record import parse_record

EXTRACTOR_INSTRUCTIONS = """\
You are a meticulous data extractor for mitochondrial-medicine evidence.

For every request you receive ONE study record (title + abstract/metadata).
Extract a single structured StudyRecord from it, following the loaded
extraction_rules skill exactly.

Hard constraints:
- The provided text is your ONLY source of truth. Never use prior knowledge.
- ref_id must be copied verbatim from the record metadata.
- First call the `validate_extraction` tool with your draft; fix every error
  it reports until it returns OK, then return the final record.
- If the abstract reports both an experimental drug and a standard-of-care
  comparator with separate results, extract ONLY the arm you are asked about.
"""

EXTRACTION_PROMPT = """\
Extract a StudyRecord for the following {kind} record.

Intervention focus: {focus}
Standard-of-care context: {soc}

--- RECORD METADATA ---
source: {source}
ref_id: {ref_id}
journal: {journal}
year: {year}
trial_phase (registry): {phase}
enrollment (registry): {enrollment}

--- TITLE ---
{title}

--- ABSTRACT / SUMMARY ---
{abstract}
"""


def build_extractor_agent(model: Any, skills: list[SkillCapability] | None = None) -> Agent[Any, StudyRecord]:
    agent: Agent[Any, StudyRecord] = Agent(
        model,
        output_type=StudyRecord,
        instructions=inject_skills(EXTRACTOR_INSTRUCTIONS, list(skills or [])),
    )

    @agent.tool_plain(retries=3)
    def validate_extraction(record: dict[str, Any]) -> str:
        """Validate a draft extraction dict against the strict StudyRecord schema.

        Returns OK when the record is valid; otherwise returns the errors the
        caller must fix (ref_id, phase, directions, evidence_level are normalized).
        """
        try:
            rec = parse_record(record)
        except ValueError as exc:
            raise ModelRetry(f"Invalid extraction: {exc}. Correct the record and call again.") from exc
        return (
            f"OK: {rec.ref_id} phase={rec.phase.value} evidence={rec.evidence_level.value} outcomes={len(rec.outcomes)}"
        )

    return agent


def extraction_prompt(record: UnifiedRecord, focus: str, soc: str) -> str:
    return EXTRACTION_PROMPT.format(
        kind=record.source.value,
        focus=focus or "any mitochondria-targeted intervention studied in this record",
        soc=soc or "n/a",
        source=record.source.value,
        ref_id=record.ref_id,
        journal=record.journal or "unknown",
        year=record.year or "unknown",
        phase=record.trial_phase or "n/a",
        enrollment=record.enrollment or "n/a",
        title=record.title,
        abstract=record.abstract or "(no abstract available - extract from title only, mark outcomes as unclear)",
    )
