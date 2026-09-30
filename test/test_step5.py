"""Step-5 acceptance: compare/evaluate/visualize handlers run offline (TestModel) and render PNGs."""

from pathlib import Path
from types import SimpleNamespace

from pydantic_ai.models.test import TestModel

from mito_harness.logging_events import EventBus, new_run_id
from mito_harness.pipeline import build_harness
from mito_harness.schemas import (
    Direction,
    EvidenceLevel,
    OutcomeMeasure,
    SourceKind,
    StepKind,
    StudyPhase,
    StudyRecord,
    UnifiedRecord,
)
from mito_harness.skills_loader import load_skills, skills_catalog
from setting import get_settings


def _bus(tmp_path: Path) -> EventBus:
    return EventBus(run_id=new_run_id(), outputs_dir=tmp_path, console_format="{ts} [{event}] {agent} {tool} {detail}")


def _studies() -> list[StudyRecord]:
    return [
        StudyRecord(
            ref_id="36100001",
            title="Elamipretide in PMD",
            source=SourceKind.pubmed,
            intervention="elamipretide",
            disease="primary mitochondrial diseases",
            design="randomized placebo-controlled trial",
            phase=StudyPhase.phase3,
            outcomes=[OutcomeMeasure(name="6MWT", direction=Direction.positive, significant=True)],
            evidence_level=EvidenceLevel.rct,
            year=2022,
        ),
        StudyRecord(
            ref_id="NCT04567890",
            title="Gene therapy for LHON",
            source=SourceKind.ctgov,
            intervention="LHON gene therapy",
            disease="Leber hereditary optic neuropathy",
            design="registry",
            phase=StudyPhase.phase3,
            outcomes=[OutcomeMeasure(name="BCVA", direction=Direction.unclear, significant=False)],
            evidence_level=EvidenceLevel.rct,
            year=2022,
        ),
    ]


def _state() -> SimpleNamespace:
    studies = _studies()
    return SimpleNamespace(
        goal="Compare mito vs standard",
        query_id="t",
        records=[
            UnifiedRecord(source=SourceKind.pubmed, title=s.title, abstract="x", pmid=s.ref_id, year=s.year)
            for s in studies
        ],
        studies=studies,
        comparison={},
        prospects={},
        plots=[],
        report_markdown="",
        review={},
        replanned=True,
    )


async def test_compare_evaluate_visualize_handlers(tmp_path: Path):
    settings = get_settings().model_copy(deep=True)
    settings.paths.outputs_dir = tmp_path
    settings.paths.cache_dir = tmp_path / "cache"
    bus = _bus(tmp_path)
    orch = build_harness(
        bus,
        settings=settings,
        search_model=TestModel(call_tools=[]),
        extract_model=TestModel(call_tools=[]),
    )
    from mito_harness.schemas import PlanStep

    state = _state()
    await orch.handlers[StepKind.compare](state, PlanStep(id="c1", kind=StepKind.compare, description="d"))
    assert state.comparison["plot_items"]

    await orch.handlers[StepKind.evaluate](state, PlanStep(id="e1", kind=StepKind.evaluate, description="d"))
    assert state.prospects["items"]

    await orch.handlers[StepKind.visualize](state, PlanStep(id="v1", kind=StepKind.visualize, description="d"))
    assert state.plots, "no plots rendered"
    for plot in state.plots:
        assert Path(plot).exists() and Path(plot).stat().st_size > 1000

    log = (tmp_path / f"run_{bus.run_id}.jsonl").read_text()
    assert "task_delegated" in log
    assert "tool_result" in log


def test_all_four_skills_present():
    s = get_settings()
    catalog = skills_catalog(load_skills(s.paths.skills_dir))
    assert {"extraction_rules", "evidence_levels", "prospects_criteria", "citation_checklist"} <= set(catalog)
