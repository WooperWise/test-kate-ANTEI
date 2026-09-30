"""Step-4 acceptance: orchestrator graph works end-to-end on TestModel with fake handlers."""

import asyncio
import json

from pydantic_ai.models.test import TestModel

from mito_harness.logging_events import EventBus, new_run_id
from mito_harness.orchestrator import Orchestrator
from mito_harness.schemas import SourceKind, StepKind, StudyRecord, UnifiedRecord
from setting import get_settings


def _two_records() -> list[UnifiedRecord]:
    return [
        UnifiedRecord(
            source=SourceKind.pubmed,
            title="Elamipretide in primary mitochondrial myopathy",
            abstract="Randomized trial, 6MWT improved by 20 m (p=0.04).",
            pmid="36100001",
            year=2022,
        ),
        UnifiedRecord(
            source=SourceKind.ctgov,
            title="Gene therapy for LHON",
            abstract="Phase 3, BCVA improvement.",
            nct_id="NCT04567890",
            year=2022,
            trial_phase="PHASE3",
        ),
    ]


def _one_study() -> StudyRecord:
    from mito_harness.schemas import Direction, EvidenceLevel, OutcomeMeasure, StudyPhase

    return StudyRecord(
        ref_id="36100001",
        title="Elamipretide in primary mitochondrial myopathy",
        source=SourceKind.pubmed,
        intervention="elamipretide",
        disease="primary mitochondrial diseases",
        design="randomized placebo-controlled trial",
        phase=StudyPhase.phase3,
        outcomes=[OutcomeMeasure(name="6MWT", direction=Direction.positive, significant=True)],
        evidence_level=EvidenceLevel.rct,
        year=2022,
    )


def _events(bus: EventBus) -> list[dict]:
    return [json.loads(line) for line in (bus.outputs_dir / f"run_{bus.run_id}.jsonl").read_text().splitlines()]


async def test_full_graph_smoke(tmp_path):
    bus = EventBus(run_id=new_run_id(), outputs_dir=tmp_path, console_format="{ts} [{event}] {agent} {tool} {detail}")

    calls: list[str] = []

    async def fake_search(state, step):
        calls.append(f"search:{step.id}")
        state.records = _two_records()

    async def fake_extract(state, step):
        calls.append(f"extract:{step.id}")
        state.studies = [_one_study()]

    async def fake_report(state, step):
        calls.append(f"report:{step.id}")
        state.report_markdown = "# Mini review\n"

    orch = Orchestrator(
        settings=get_settings(),
        bus=bus,
        plan_model=TestModel(call_tools=[]),
        handlers={
            StepKind.search: fake_search,
            StepKind.extract: fake_extract,
            StepKind.report: fake_report,
        },
    )
    result = await orch.run_query("demo", "Compare mito drugs vs standard care")

    assert result.status == "ok"
    assert calls, "no handler executed"
    assert calls[0].startswith("search:")
    assert calls[-1].startswith("report:")
    assert len(result.records) == 1

    events = _events(bus)
    kinds = [e["event"] for e in events]
    assert "run_started" in kinds
    assert "plan_created" in kinds
    assert "run_finished" in kinds
    plan_created = next(e for e in events if e["event"] == "plan_created")
    assert plan_created["payload"]["steps"]


async def test_sparse_results_trigger_replan(tmp_path):
    bus = EventBus(run_id=new_run_id(), outputs_dir=tmp_path, console_format="{ts} [{event}] {agent} {tool} {detail}")

    async def sparse_search(state, step):
        state.records = _two_records()[:1]

    orch = Orchestrator(
        settings=get_settings(),
        bus=bus,
        plan_model=TestModel(call_tools=[]),
        handlers={StepKind.search: sparse_search},
    )
    await orch.run_query("demo", "narrow query")

    events = _events(bus)
    assert any(e["event"] == "plan_adjusted" and "sparse" in e["payload"]["reason"] for e in events)


async def test_wall_clock_degradation(tmp_path):
    bus = EventBus(run_id=new_run_id(), outputs_dir=tmp_path, console_format="{ts} [{event}] {agent} {tool} {detail}")

    async def slow_search(state, step):
        await asyncio.sleep(5)
        state.records = _two_records()

    settings = get_settings().model_copy(deep=True)
    settings.limits.wall_clock_minutes = 0

    orch = Orchestrator(
        settings=settings,
        bus=bus,
        plan_model=TestModel(call_tools=[]),
        handlers={StepKind.search: slow_search},
    )
    result = await orch.run_query("demo", "query that will time out")
    assert result.status == "degraded"
    events = _events(bus)
    assert any(e["event"] == "budget_degraded" for e in events)
