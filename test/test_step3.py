"""Step-3 acceptance: skills load from markdown, extractor returns a valid StudyRecord (TestModel)."""

import pytest
from pydantic_ai.models.test import TestModel

from mito_harness.agents.data_extractor import build_extractor_agent, extraction_prompt
from mito_harness.schemas import SourceKind, StudyRecord, UnifiedRecord
from mito_harness.skills_loader import (
    SkillCapability,
    load_skills,
    parse_skill_file,
    skills_catalog,
)
from setting import get_settings


def test_two_skills_load_from_catalog():
    s = get_settings()
    caps = load_skills(s.paths.skills_dir)
    catalog = skills_catalog(caps)
    assert "extraction_rules" in catalog
    assert "evidence_levels" in catalog
    for cap in caps:
        assert isinstance(cap, SkillCapability)
        assert len(cap.get_instructions()) > 200


def test_skills_can_defer_progressively(tmp_path):
    s = get_settings()
    caps = load_skills(s.paths.skills_dir, deferred=True)
    assert all(c.defer_loading is True for c in caps)


def test_skill_activation_logged(tmp_path):
    from mito_harness.logging_events import EventBus, new_run_id

    bus = EventBus(run_id=new_run_id(), outputs_dir=tmp_path, console_format="{ts} [{event}] {agent} {tool} {detail}")
    s = get_settings()
    caps = load_skills(s.paths.skills_dir, bus=bus)
    target = next(c for c in caps if c.id == "extraction_rules")
    target.get_instructions()  # activation
    lines = (tmp_path / f"run_{bus.run_id}.jsonl").read_text().strip().splitlines()
    assert any('"skill_loaded"' in line and "extraction_rules" in line for line in lines)
    # second activation is not double-logged
    target.get_instructions()
    lines2 = (tmp_path / f"run_{bus.run_id}.jsonl").read_text().strip().splitlines()
    assert len(lines2) == len(lines)


def test_parse_skill_file_rejects_missing_description(tmp_path):
    bad = tmp_path / "SKILL.md"
    bad.write_text("---\nid: x\n---\nbody")
    with pytest.raises(ValueError, match="description"):
        parse_skill_file(bad)


@pytest.mark.asyncio
async def test_extractor_agent_offline():
    """TestModel: no LLM, produces a schema-valid StudyRecord output."""

    agent = build_extractor_agent(TestModel(call_tools=[]))
    record = UnifiedRecord(
        source=SourceKind.pubmed,
        title="Elamipretide in primary mitochondrial myopathy",
        abstract="Randomized trial. 6MWT improved.",
        pmid="36100001",
        year=2022,
    )
    prompt = extraction_prompt(record, focus="elamipretide", soc="supportive care")
    result = await agent.run(prompt)
    assert isinstance(result.output, StudyRecord)
    assert result.output.outcomes  # at least one outcome per schema


def test_extraction_prompt_contains_record_only():
    record = UnifiedRecord(
        source=SourceKind.ctgov,
        title="MitoQ in Parkinson's",
        abstract=None,
        nct_id="NCT04567890",
        year=2022,
        trial_phase="PHASE2",
        enrollment=120,
    )
    prompt = extraction_prompt(record, focus="MitoQ", soc="levodopa")
    assert "NCT04567890" in prompt
    assert "no abstract available" in prompt
