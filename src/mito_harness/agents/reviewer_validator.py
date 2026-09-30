"""ReviewerValidatorAgent: verifies citations/numbers/claims before approval.

Tools: verify_citation (re-fetch PMID/NCT/DOI). Skills: citation_checklist.
The orchestrator's review handler drives up to `max_review_iterations`
fix rounds; unresolved findings trigger de-escalation (claims removed).
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext

from mito_harness.schemas import ReviewVerdict, VerifyResult
from mito_harness.skills_loader import SkillCapability, inject_skills
from mito_harness.tools.verify_citation import verify_citation as verify_citation_impl

REVIEWER_INSTRUCTIONS = """\
You are the reviewer-validator of a mitochondrial-medicine research harness.

You receive a report draft plus the underlying extracted StudyRecords. Follow
the loaded citation_checklist skill exactly. Call the `check_citation` tool for
the MOST IMPORTANT reference ids used by the draft (up to 12; prioritize claims
from the summary, directions and outsiders sections).

Verdict rules:
- approved=true ONLY when no blocking findings remain.
- Report AT MOST 10 findings, prioritizing blocking ones (REMOVE before FIX).
- Each finding carries location (section), issue, action (FIX/REMOVE/VERIFY)
  and the ref_id it concerns (when applicable).
- Numbers without provenance in the records => action REMOVE.
- Never approve a claim whose citation check returned verified=false.
"""

REVIEW_PROMPT = """\
Review the following report draft for citation and factual integrity.

--- REPORT DRAFT (markdown) ---
{draft}

--- VERIFIED-DATA SNAPSHOT ---
Records used ({n_records}):
{records_digest}

Citation checks you must perform with check_citation for every ref_id used above:
{ref_ids}
"""


def build_reviewer_agent(model: Any, skills: list[SkillCapability] | None = None) -> Agent[Any, ReviewVerdict]:
    agent: Agent[Any, ReviewVerdict] = Agent(
        model,
        output_type=ReviewVerdict,
        instructions=inject_skills(REVIEWER_INSTRUCTIONS, list(skills or [])),
    )

    @agent.tool
    async def check_citation(ctx: RunContext[Any], identifier: str, claimed_title: str) -> str:
        """Re-fetch PMID/NCT/DOI from the live registry and check title/year match."""
        result: VerifyResult = await verify_citation_impl(identifier, claimed_title)
        return (
            f"verified={result.verified} similarity={result.title_similarity} "
            f"fetched_title={result.fetched_title!r} reason={result.reason}"
        )

    return agent


def review_prompt(draft_markdown: str, studies: list[Any]) -> str:
    digest_lines = [
        f"- {s.ref_id} [{s.evidence_level.value}/{s.phase.value}] {s.intervention} in {s.disease}: "
        f"{', '.join(f'{o.name}:{o.direction.value}' for o in s.outcomes)}"
        for s in studies
    ]
    ref_ids = "\n".join(sorted({s.ref_id for s in studies}))
    return REVIEW_PROMPT.format(
        draft=draft_markdown[:5500],
        n_records=len(studies),
        records_digest="\n".join(digest_lines),
        ref_ids=ref_ids,
    )
