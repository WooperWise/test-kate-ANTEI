"""ProspectsEvaluatorAgent: weighted scoring of therapy directions.

Weights and scoring rules live in the prospects_criteria skill (runtime-injected),
NOT in code: changing the rubric must not require a code change.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from mito_harness.schemas import ProspectsAssessment
from mito_harness.skills_loader import SkillCapability, inject_skills

EVALUATOR_INSTRUCTIONS = """\
You are the prospects evaluator of a mitochondrial-medicine research harness.

Score AT MOST THE TOP 8 directions (intervention x disease pairs with the
highest density of evidence; merge class-level reviews into their drug class)
using the loaded prospects_criteria skill rubric EXACTLY: five components 0-10,
the weights defined in the skill, weighted total rounded to 1 decimal.

Rules:
- Base every component score on the provided StudyRecords; cite ref_ids in rationales.
- Respect the skill's caps: negative phase-3 evidence caps effect_direction at 3;
  thin evidence (<2 ref_ids) caps the total at 4.
- leaders: only totals >= 6, ordered; outsiders: bottom quartile with reasons.
- caveats: methodological limitations affecting the scoring (sparse data, surrogate
  outcomes, single-study directions).
- Output ProspectsAssessment with items sorted by total descending.
- Keep every rationale under 40 words: brevity keeps the run inside budget.
"""


def build_evaluator_agent(model: Any, skills: list[SkillCapability] | None = None) -> Agent[Any, ProspectsAssessment]:
    return Agent(
        model,
        output_type=ProspectsAssessment,
        instructions=inject_skills(EVALUATOR_INSTRUCTIONS, list(skills or [])),
    )


def evaluation_prompt(studies_json: str, comparison_summary: str, standards_json: str) -> str:
    return (
        "Score the promise of each direction (intervention x disease) covered by the evidence below.\n\n"
        f"--- STANDARD-OF-CARE MAP ---\n{standards_json}\n\n"
        f"--- EXTRACTED STUDY RECORDS (JSON) ---\n{studies_json}\n\n"
        f"--- COMPARISON INSIGHTS ---\n{comparison_summary}\n"
    )
