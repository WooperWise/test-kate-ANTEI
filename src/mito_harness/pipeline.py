"""Pipeline wiring: builds the real harness (agents, tools, skills, handlers).

Search and extraction handlers are live here; comparison/evaluation/
visualization/review/report handlers are attached by later build steps
(compare/evaluate/visualize in step 5, review/report in step 6).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mito_harness.agents.base import build_model, run_agent_logged
from mito_harness.agents.comparative_analyst import build_comparison_agent, comparison_prompt
from mito_harness.agents.data_extractor import build_extractor_agent, extraction_prompt
from mito_harness.agents.literature_search import build_search_planner, search_prompt
from mito_harness.agents.prospects_evaluator import build_evaluator_agent, evaluation_prompt
from mito_harness.agents.reviewer_validator import build_reviewer_agent, review_prompt
from mito_harness.agents.visualizer import build_visualizer_agent, visualization_prompt
from mito_harness.cache import DiskCache
from mito_harness.logging_events import EventBus
from mito_harness.orchestrator import Orchestrator, RunState
from mito_harness.reporting import assemble_markdown, build_reporter_agent, reporter_prompt
from mito_harness.schemas import (
    ComparisonResult,
    PlanStep,
    ProspectsAssessment,
    ReportNarrative,
    ReviewVerdict,
    SearchPlan,
    SourceKind,
    StepKind,
    StudyRecord,
    UnifiedRecord,
    VisualizationSpec,
)
from mito_harness.skills_loader import SkillCapability, load_skills
from mito_harness.tools import ctgov_search, europepmc_search, pubmed_search
from mito_harness.tools.compute_plot import (
    effect_direction_plot,
    evidence_gap_map,
    prospects_ranking,
)
from setting import Settings, get_settings

logger = logging.getLogger(__name__)


async def _run_source_query(
    source: SourceKind, terms: str, window: dict[str, Any], max_results: int
) -> list[UnifiedRecord]:
    if source is SourceKind.pubmed:
        return await pubmed_search(terms, window["from_year"], window["to_year"], max_results)
    if source is SourceKind.europepmc:
        return await europepmc_search(terms, window["from_year"], window["to_year"], max_results)
    if source is SourceKind.ctgov:
        return await ctgov_search(terms, window["from_year"], window["to_year"], max_results)
    return []


def dedup_records(records: list[UnifiedRecord], limit: int) -> list[UnifiedRecord]:
    seen: set[str] = set()
    unique: list[UnifiedRecord] = []
    for rec in records:
        key = rec.nct_id or rec.pmid or rec.doi or rec.title.lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        unique.append(rec)
    return unique[:limit]


def make_search_handler(settings: Settings, bus: EventBus, search_model: Any) -> Any:
    planner = build_search_planner(search_model)
    llm_cache = DiskCache(settings.paths.cache_dir)

    async def handle_search(state: RunState, step: PlanStep) -> None:
        window = dict(settings.queries_config.get("window", {"from_year": 2021, "to_year": 2026}))
        scope = {
            "diseases": [d["name"] for d in settings.queries_config.get("diseases", [])],
            "interventions": [i["label"] for i in settings.queries_config.get("mito_interventions", [])],
        }
        prompt = search_prompt(
            state.goal, window["from_year"], window["to_year"], settings.limits.max_records, str(scope)
        )
        if step.params.get("forced_terms"):
            plan = SearchPlan.model_validate(
                {
                    "queries": [
                        {"source": src, "terms": str(step.params["forced_terms"])}
                        for src in step.params.get("sources", ["pubmed", "europepmc"])
                    ]
                }
            )
        else:
            plan = await run_agent_cached(
                planner,
                prompt,
                bus=bus,
                agent_name="literature_search",
                step_id=step.id,
                correlation_id=step.id,
                cache=llm_cache,
                cache_ns="llm_plan",
                model_cls=SearchPlan,
            )

        per_query_cap = max(3, settings.limits.max_records // max(len(plan.queries), 1))
        tasks = [_run_source_query(q.source, q.terms, window, per_query_cap) for q in plan.queries]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        fresh: list[UnifiedRecord] = []
        for query, outcome in zip(plan.queries, gathered, strict=False):
            if isinstance(outcome, BaseException):
                bus.emit(
                    "task_failed",
                    agent="literature_search",
                    tool=f"{query.source.value}_search",
                    step_id=step.id,
                    payload={"terms": query.terms[:120], "error": str(outcome)[:200]},
                )
                continue
            bus.emit(
                "tool_result",
                agent="literature_search",
                tool=f"{query.source.value}_search",
                step_id=step.id,
                payload={"terms": query.terms[:120], "hits": len(outcome)},
            )
            fresh.extend(outcome)
        merged = dedup_records(state.records + fresh, settings.limits.max_records)
        state.records = merged

    return handle_search


def make_extract_handler(settings: Settings, bus: EventBus, extract_model: Any, skills: list[SkillCapability]) -> Any:
    wanted_ids = {"extraction_rules"}
    extractor = build_extractor_agent(extract_model, [c for c in skills if c.id in wanted_ids])
    diseases = {d["name"]: d for d in settings.queries_config.get("diseases", [])}
    extraction_cache = DiskCache(settings.paths.cache_dir)

    async def handle_extract(state: RunState, step: PlanStep) -> None:
        focus_hint = ", ".join(step.params.get("diseases", [])) or None
        already_extracted = {s.ref_id for s in state.studies}
        records = [r for r in state.records if r.abstract and r.ref_id not in already_extracted]
        if not records:
            bus.emit(
                "task_skipped",
                agent="data_extractor",
                step_id=step.id,
                payload={"reason": "all records already extracted (idempotent re-run)"},
            )
            return
        soc_by_disease = {name: d.get("standard_of_care", "") for name, d in diseases.items()}

        async def extract_one(record: UnifiedRecord) -> StudyRecord | None:
            focus = step.params.get("interventions", ["any mitochondria-targeted intervention"])[0]
            if focus_hint:
                focus = f"{focus} (disease focus: {focus_hint})"
            cache_key = {"ref_id": record.ref_id, "focus": focus}
            cached = extraction_cache.get("llm_extract", cache_key)
            if cached is not None:
                bus.emit(
                    "tool_result",
                    agent="data_extractor",
                    tool="llm_cache",
                    step_id=step.id,
                    correlation_id=record.ref_id,
                    payload={"hit": True},
                )
                return StudyRecord.model_validate(cached)
            soc = next((v for k, v in soc_by_disease.items() if k.lower() in record.title.lower()), "")
            prompt = extraction_prompt(record, focus=focus, soc=soc)
            try:
                output = await run_agent_logged(
                    extractor,
                    prompt,
                    bus=bus,
                    agent_name="data_extractor",
                    step_id=step.id,
                    correlation_id=record.ref_id,
                )
                study = StudyRecord.model_validate(output)
                extraction_cache.set("llm_extract", cache_key, study.model_dump())
                return study
            except Exception as exc:
                bus.emit(
                    "task_failed",
                    agent="data_extractor",
                    step_id=step.id,
                    correlation_id=record.ref_id,
                    payload={"error": str(exc)[:200]},
                )
                return None

        results = await asyncio.gather(*(extract_one(r) for r in records))
        state.studies.extend(s for s in results if s is not None)

    return handle_extract


def studies_digest(studies: list[StudyRecord]) -> str:
    """Compact JSON view of studies for analysis prompts (keeps token budget sane)."""
    keys = (
        "ref_id",
        "intervention",
        "intervention_class",
        "disease",
        "is_standard_of_care",
        "design",
        "phase",
        "n_participants",
        "outcomes",
        "evidence_level",
        "year",
    )
    compact = [{k: s.model_dump()[k] for k in keys} for s in studies]
    import json as _json

    return _json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


async def run_agent_cached(
    agent: Any,
    prompt: str,
    *,
    bus: EventBus,
    agent_name: str,
    step_id: str,
    correlation_id: str,
    cache: DiskCache,
    cache_ns: str,
    model_cls: Any,
) -> Any:
    """LLM call with a disk cache keyed by (agent, prompt) for reproducible fast reruns."""
    key = {"agent": agent_name, "prompt_hash": __import__("hashlib").sha256(prompt.encode()).hexdigest()}
    cached = cache.get(cache_ns, key)
    if cached is not None:
        bus.emit("tool_result", agent=agent_name, tool="llm_cache", step_id=step_id, payload={"hit": True})
        return model_cls.model_validate(cached)
    output = await run_agent_logged(
        agent, prompt, bus=bus, agent_name=agent_name, step_id=step_id, correlation_id=correlation_id
    )
    parsed = model_cls.model_validate(output)
    cache.set(cache_ns, key, parsed.model_dump())
    return parsed


def make_compare_handler(settings: Settings, bus: EventBus, compare_model: Any, skills: list[SkillCapability]) -> Any:
    analyst = build_comparison_agent(compare_model, [c for c in skills if c.id == "evidence_levels"])
    llm_cache = DiskCache(settings.paths.cache_dir)

    async def handle_compare(state: RunState, step: PlanStep) -> None:
        if not state.studies:
            bus.emit("task_skipped", agent="comparative_analyst", step_id=step.id, payload={"reason": "no studies"})
            return
        standards = {d["name"]: d.get("standard_of_care", "") for d in settings.queries_config.get("diseases", [])}
        studies_json = studies_digest(state.studies)
        result = await run_agent_cached(
            analyst,
            comparison_prompt(studies_json, str(standards)),
            bus=bus,
            agent_name="comparative_analyst",
            step_id=step.id,
            correlation_id=step.id,
            cache=llm_cache,
            cache_ns="llm_compare",
            model_cls=ComparisonResult,
        )
        state.comparison = result.model_dump()
        bus.emit(
            "tool_result",
            agent="comparative_analyst",
            step_id=step.id,
            payload={"plot_items": len(result.plot_items), "gap_cells": len(result.gap_cells)},
        )

    return handle_compare


def make_evaluate_handler(settings: Settings, bus: EventBus, evaluate_model: Any, skills: list[SkillCapability]) -> Any:
    evaluator = build_evaluator_agent(evaluate_model, [c for c in skills if c.id == "prospects_criteria"])
    llm_cache = DiskCache(settings.paths.cache_dir)

    async def handle_evaluate(state: RunState, step: PlanStep) -> None:
        if not state.studies:
            bus.emit("task_skipped", agent="prospects_evaluator", step_id=step.id, payload={"reason": "no studies"})
            return
        standards = {d["name"]: d.get("standard_of_care", "") for d in settings.queries_config.get("diseases", [])}
        studies_json = studies_digest(state.studies)
        insights = state.comparison.get("insights", [])
        assessment = await run_agent_cached(
            evaluator,
            evaluation_prompt(studies_json, "\n".join(insights), str(standards)),
            bus=bus,
            agent_name="prospects_evaluator",
            step_id=step.id,
            correlation_id=step.id,
            cache=llm_cache,
            cache_ns="llm_evaluate",
            model_cls=ProspectsAssessment,
        )
        state.prospects = assessment.model_dump()
        bus.emit(
            "tool_result",
            agent="prospects_evaluator",
            step_id=step.id,
            payload={"leaders": assessment.leaders, "outsiders": assessment.outsiders},
        )

    return handle_evaluate


def make_visualize_handler(settings: Settings, bus: EventBus, viz_model: Any) -> Any:
    visualizer = build_visualizer_agent(viz_model)

    async def handle_visualize(state: RunState, step: PlanStep) -> None:
        comparison = state.comparison
        prospects = state.prospects
        if not comparison.get("plot_items"):
            bus.emit("task_skipped", agent="visualizer", step_id=step.id, payload={"reason": "nothing to plot"})
            return
        diseases = [d["name"] for d in settings.queries_config.get("diseases", [])]
        spec_output = await run_agent_logged(
            visualizer,
            visualization_prompt(state.goal, diseases, prospects.get("leaders", []), prospects.get("outsiders", [])),
            bus=bus,
            agent_name="visualizer",
            step_id=step.id,
            correlation_id=step.id,
        )
        spec = VisualizationSpec.model_validate(spec_output)
        state.plot_titles = {
            "direction": spec.direction_plot_title,
            "ranking": spec.ranking_title,
            "gapmap": spec.gapmap_title,
        }
        out_dir = settings.paths.outputs_dir / f"run_{bus.run_id}"
        bus.emit("tool_called", agent="visualizer", tool="compute_plot", step_id=step.id)

        from mito_harness.schemas import DirectionPlotItem, GapCell, ProspectsItem

        p1 = effect_direction_plot(
            [DirectionPlotItem.model_validate(i) for i in comparison["plot_items"]],
            out_dir / "effect_direction.png",
            spec.direction_plot_title,
        )
        state.plots.append(str(p1))
        if prospects.get("items"):
            p2 = prospects_ranking(
                [ProspectsItem.model_validate(i) for i in prospects["items"]],
                out_dir / "prospects_ranking.png",
                spec.ranking_title,
            )
            state.plots.append(str(p2))
        if comparison.get("gap_cells"):
            p3 = evidence_gap_map(
                [GapCell.model_validate(c) for c in comparison["gap_cells"]],
                out_dir / "gap_map.png",
                spec.gapmap_title,
            )
            state.plots.append(str(p3))
        bus.emit(
            "tool_result", agent="visualizer", tool="compute_plot", step_id=step.id, payload={"png": len(state.plots)}
        )

    return handle_visualize


def make_report_handler(settings: Settings, bus: EventBus, report_model: Any) -> Any:
    reporter = build_reporter_agent(report_model)
    llm_cache = DiskCache(settings.paths.cache_dir)

    async def handle_report(state: RunState, step: PlanStep) -> None:
        if not state.studies:
            bus.emit("task_skipped", agent="reporter", step_id=step.id, payload={"reason": "no studies"})
            return
        narrative = await run_agent_cached(
            reporter,
            reporter_prompt(state),
            bus=bus,
            agent_name="reporter",
            step_id=step.id,
            correlation_id=step.id,
            cache=llm_cache,
            cache_ns="llm_report",
            model_cls=ReportNarrative,
        )
        state.review = {"narrative": narrative.model_dump()}
        state.report_markdown = assemble_markdown(state, narrative, None)
        out = settings.paths.outputs_dir / f"run_{bus.run_id}" / f"report_{state.query_id}_draft.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(state.report_markdown, encoding="utf-8")
        bus.emit(
            "tool_result",
            agent="reporter",
            tool="assemble_markdown",
            step_id=step.id,
            payload={"draft_chars": len(state.report_markdown)},
        )

    return handle_report


def _purge_rejected_refs(state: RunState, rejected: set[str]) -> None:
    """Drop reviewer-rejected ref_ids from comparison plot items and gap cells."""
    level_rank = {"preclinical": 1, "observational": 2, "rct": 3, "meta": 4}
    items = [i for i in state.comparison.get("plot_items", []) if i.get("ref_id") not in rejected]
    ref_levels: dict[str, str] = {}
    for item in items:
        ref = item.get("ref_id")
        level = str(item.get("evidence", "preclinical"))
        if ref and level_rank.get(level, 0) > level_rank.get(ref_levels.get(ref, ""), 0):
            ref_levels[ref] = level
    cells = []
    for raw in state.comparison.get("gap_cells", []):
        cell = dict(raw)
        refs = [r for r in cell.get("refs", []) if r not in rejected]
        cell["refs"] = refs
        cell["n_studies"] = len(refs)
        levels = [ref_levels[r] for r in refs if r in ref_levels]
        cell["top_evidence"] = max(levels, key=lambda lv: level_rank[lv]) if levels else None
        cells.append(cell)
    state.comparison = {**state.comparison, "plot_items": items, "gap_cells": cells}


def _rerender_plots_after_review(state: RunState, settings: Settings, bus: EventBus, step: PlanStep) -> None:
    """Re-render direction plot and gap map so figures match the post-review data."""
    from mito_harness.schemas import DirectionPlotItem, GapCell

    if not state.comparison.get("plot_items"):
        return
    out_dir = settings.paths.outputs_dir / f"run_{bus.run_id}"
    bus.emit("tool_called", agent="reviewer_validator", tool="compute_plot", step_id=step.id)
    titles = state.plot_titles
    p1 = effect_direction_plot(
        [DirectionPlotItem.model_validate(i) for i in state.comparison["plot_items"]],
        out_dir / "effect_direction.png",
        titles.get("direction", "Effect direction: mito-targeted therapy vs standard"),
    )
    rendered = [str(p1)]
    if state.comparison.get("gap_cells"):
        p2 = evidence_gap_map(
            [GapCell.model_validate(c) for c in state.comparison["gap_cells"]],
            out_dir / "gap_map.png",
            titles.get("gapmap", "Evidence gap map: intervention x disease"),
        )
        rendered.append(str(p2))
    bus.emit(
        "tool_result",
        agent="reviewer_validator",
        tool="compute_plot",
        step_id=step.id,
        payload={"rerendered": len(rendered)},
    )


def make_review_handler(settings: Settings, bus: EventBus, review_model: Any, skills: list[SkillCapability]) -> Any:
    reviewer = build_reviewer_agent(review_model, [c for c in skills if c.id == "citation_checklist"])
    reporter = build_reporter_agent(review_model)
    llm_cache = DiskCache(settings.paths.cache_dir)
    max_iterations = settings.limits.max_review_iterations

    def findings_note(verdict: ReviewVerdict) -> str:
        return "\n".join(f"- [{f.action}] {f.location}: {f.issue} (ref={f.ref_id or '-'})" for f in verdict.findings)

    async def handle_review(state: RunState, step: PlanStep) -> None:
        if not state.report_markdown:
            bus.emit("task_skipped", agent="reviewer_validator", step_id=step.id, payload={"reason": "no draft"})
            return
        verdict = ReviewVerdict(approved=False, summary="not reviewed yet", findings=[])
        narrative_raw = state.review.get("narrative")
        narrative = ReportNarrative.model_validate(narrative_raw) if narrative_raw else None

        for iteration in range(1, max_iterations + 1):
            verdict = await run_agent_cached(
                reviewer,
                review_prompt(state.report_markdown, state.studies),
                bus=bus,
                agent_name="reviewer_validator",
                step_id=step.id,
                correlation_id=f"{step.id}#{iteration}",
                cache=llm_cache,
                cache_ns="llm_review",
                model_cls=ReviewVerdict,
            )
            bus.emit(
                "review_feedback",
                agent="reviewer_validator",
                step_id=step.id,
                payload={
                    "iteration": iteration,
                    "approved": verdict.approved,
                    "findings": len(verdict.findings),
                },
            )
            if verdict.approved:
                break
            if iteration < max_iterations:
                narrative = await run_agent_cached(
                    reporter,
                    reporter_prompt(state, corrections=findings_note(verdict)),
                    bus=bus,
                    agent_name="reporter",
                    step_id=step.id,
                    correlation_id=f"{step.id}#fix{iteration}",
                    cache=llm_cache,
                    cache_ns="llm_report",
                    model_cls=ReportNarrative,
                )
                state.report_markdown = assemble_markdown(state, narrative, verdict)

        if not verdict.approved:
            bus.emit(
                "iteration_exhausted",
                agent="reviewer_validator",
                step_id=step.id,
                payload={"iterations": max_iterations, "action": "de-escalation: removing unverified claims"},
            )
            rejected_refs = {f.ref_id for f in verdict.findings if f.action == "REMOVE" and f.ref_id}
            if rejected_refs:
                state.studies = [s for s in state.studies if s.ref_id not in rejected_refs]
                _purge_rejected_refs(state, rejected_refs)
                _rerender_plots_after_review(state, settings, bus, step)
            narrative = await run_agent_cached(
                reporter,
                reporter_prompt(state, corrections=findings_note(verdict)),
                bus=bus,
                agent_name="reporter",
                step_id=step.id,
                correlation_id=f"{step.id}#deescalation",
                cache=llm_cache,
                cache_ns="llm_report",
                model_cls=ReportNarrative,
            )

        if narrative is not None:
            state.report_markdown = assemble_markdown(state, narrative, verdict)
            state.review = {"narrative": narrative.model_dump(), "verdict": verdict.model_dump()}
            out = settings.paths.outputs_dir / f"run_{bus.run_id}" / f"report_{state.query_id}.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(state.report_markdown, encoding="utf-8")
            bus.emit(
                "tool_result",
                agent="reviewer_validator",
                tool="assemble_markdown",
                step_id=step.id,
                payload={"final_report": str(out), "approved": verdict.approved},
            )

    return handle_review


def build_harness(
    bus: EventBus,
    settings: Settings | None = None,
    search_model: Any = None,
    extract_model: Any = None,
    extra_handlers: dict[StepKind, Any] | None = None,
) -> Orchestrator:
    """Assemble the full harness; models default to the configured endpoint."""
    s = settings or get_settings()
    skills = load_skills(s.paths.skills_dir, bus=bus)
    search_model = search_model or build_model(s)
    extract_model = extract_model or build_model(s)

    orchestrator = Orchestrator(settings=s, bus=bus, plan_model=search_model)
    orchestrator.on(StepKind.search, make_search_handler(s, bus, search_model))
    orchestrator.on(StepKind.extract, make_extract_handler(s, bus, extract_model, skills))
    orchestrator.on(StepKind.compare, make_compare_handler(s, bus, extract_model, skills))
    orchestrator.on(StepKind.evaluate, make_evaluate_handler(s, bus, extract_model, skills))
    orchestrator.on(StepKind.visualize, make_visualize_handler(s, bus, extract_model))
    orchestrator.on(StepKind.report, make_report_handler(s, bus, extract_model))
    orchestrator.on(StepKind.review, make_review_handler(s, bus, extract_model, skills))
    for kind, handler in (extra_handlers or {}).items():
        orchestrator.on(kind, handler)
    return orchestrator
