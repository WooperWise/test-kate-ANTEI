"""Step-6 acceptance: report assembly + reviewer loop with de-escalation (offline)."""

import json
from pathlib import Path
from types import SimpleNamespace

from pydantic_ai.models.test import TestModel

from mito_harness.logging_events import EventBus, new_run_id
from mito_harness.pipeline import build_harness
from mito_harness.reporting import ReportNarrative, assemble_markdown
from mito_harness.schemas import (
    Direction,
    EvidenceLevel,
    OutcomeMeasure,
    ReviewFinding,
    ReviewVerdict,
    SourceKind,
    StepKind,
    StudyPhase,
    StudyRecord,
)
from setting import get_settings


def _state(tmp_path: Path) -> SimpleNamespace:
    studies = [
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
            outcomes=[OutcomeMeasure(name="BCVA", direction=Direction.unclear)],
            evidence_level=EvidenceLevel.rct,
            year=2022,
        ),
    ]
    return SimpleNamespace(
        goal="Compare mito vs standard",
        query_id="t",
        records=[],
        studies=studies,
        comparison={"insights": ["elamipretide RCT positive (36100001)"]},
        prospects={
            "items": [
                {
                    "label": "elamipretide / PMD",
                    "total": 6.5,
                    "components": [{"name": "evidence_quality", "score": 7, "weight": 0.3}],
                    "rationale": "RCT (36100001)",
                }
            ],
            "leaders": ["elamipretide / PMD"],
            "outsiders": [],
        },
        plots=[],
        report_markdown="",
        review={},
        replanned=True,
    )


def _narrative() -> ReportNarrative:
    return ReportNarrative(
        summary=["Эламипретид показал улучшение 6MWT в РКТ (36100001)."],
        methods_notes=["Пул: 2 записи, окно 2021-2026."],
        directions_analysis=["Направление лидирует за счёт РКТ (36100001)."],
        outsiders_analysis=["Данных мало."],
        limitations=["Экспресс-обзор без мета-анализа."],
    )


def test_assemble_markdown_sections(tmp_path):
    state = _state(tmp_path)
    md = assemble_markdown(state, _narrative(), None)
    for section in [
        "## 1. Резюме",
        "## 2. Методы",
        "## 3. Сравнительная матрица",
        "## 4. Наиболее перспективные",
        "## 5. Аутсайдеры",
        "## 6. Ограничения",
        "## 7. Ссылки",
        "## 8. Отклонено ревьюером",
    ]:
        assert section in md
    assert "36100001" in md and "NCT04567890" in md
    assert "https://pubmed.ncbi.nlm.nih.gov/36100001/" in md
    assert "не является медицинской рекомендацией" in md


def test_assemble_markdown_includes_findings(tmp_path):
    state = _state(tmp_path)
    verdict = ReviewVerdict(
        approved=False,
        summary="одно утверждение без подтверждения",
        findings=[ReviewFinding(location="4", issue="нет источника", action="REMOVE", ref_id="36100001")],
    )
    md = assemble_markdown(state, _narrative(), verdict)
    assert "нет источника" in md


def test_purge_and_rerender_after_review(tmp_path):
    """De-escalation must purge rejected refs from comparison data and re-render plots."""
    from mito_harness.logging_events import EventBus, new_run_id
    from mito_harness.pipeline import _purge_rejected_refs, _rerender_plots_after_review
    from setting import get_settings

    state = _state(tmp_path)
    state.comparison = {
        "plot_items": [
            {
                "study_label": "S1 (Ph2)",
                "outcome": "6MWT",
                "arm": "mito",
                "direction": "positive",
                "significant": True,
                "evidence": "rct",
                "ref_id": "11111111",
            },
            {
                "study_label": "S2 (Ph1)",
                "outcome": "BCVA",
                "arm": "mito",
                "direction": "negative",
                "significant": False,
                "evidence": "preclinical",
                "ref_id": "22222222",
            },
        ],
        "gap_cells": [
            {
                "intervention": "elamipretide",
                "disease": "PMD",
                "n_studies": 2,
                "top_evidence": "preclinical",
                "refs": ["11111111", "22222222"],
            }
        ],
    }
    state.plot_titles = {"direction": "dir title", "gapmap": "gap title"}

    _purge_rejected_refs(state, {"22222222"})
    assert [i["ref_id"] for i in state.comparison["plot_items"]] == ["11111111"]
    cell = state.comparison["gap_cells"][0]
    assert cell["refs"] == ["11111111"]
    assert cell["n_studies"] == 1
    assert cell["top_evidence"] == "rct"  # recomputed from remaining items

    settings = get_settings().model_copy(deep=True)
    settings.paths.outputs_dir = tmp_path
    settings.paths.cache_dir = tmp_path / "cache"
    bus = EventBus(run_id=new_run_id(), outputs_dir=tmp_path, console_format="{ts} [{event}] {agent} {tool} {detail}")
    from mito_harness.schemas import PlanStep

    _rerender_plots_after_review(state, settings, bus, PlanStep(id="rv", kind=StepKind.review, description="d"))
    assert (tmp_path / f"run_{bus.run_id}" / "effect_direction.png").exists()
    assert (tmp_path / f"run_{bus.run_id}" / "gap_map.png").exists()
    log = (tmp_path / f"run_{bus.run_id}.jsonl").read_text()
    assert "compute_plot" in log


async def test_review_loop_deescalation(tmp_path):
    """TestModel returns approved=False -> 3 iterations -> de-escalation path."""
    settings = get_settings().model_copy(deep=True)
    settings.paths.outputs_dir = tmp_path
    settings.paths.cache_dir = tmp_path / "cache"
    settings.limits.max_review_iterations = 2
    bus = EventBus(run_id=new_run_id(), outputs_dir=tmp_path, console_format="{ts} [{event}] {agent} {tool} {detail}")
    orch = build_harness(
        bus,
        settings=settings,
        search_model=TestModel(call_tools=[]),
        extract_model=TestModel(call_tools=[]),
    )
    from mito_harness.schemas import PlanStep

    state = _state(tmp_path)

    await orch.handlers[StepKind.report](state, PlanStep(id="r1", kind=StepKind.report, description="d"))
    assert state.report_markdown and "## 1. Резюме" in state.report_markdown

    await orch.handlers[StepKind.review](state, PlanStep(id="v1", kind=StepKind.review, description="d"))
    log_path = tmp_path / f"run_{bus.run_id}.jsonl"
    events = [json.loads(line) for line in log_path.read_text().splitlines()]
    kinds = [e["event"] for e in events]
    assert "review_feedback" in kinds
    assert "iteration_exhausted" in kinds
    final_reports = list((tmp_path / f"run_{bus.run_id}").glob("report_t.md"))
    assert final_reports and final_reports[0].stat().st_size > 500
