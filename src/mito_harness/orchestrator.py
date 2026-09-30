"""RootOrchestrator: metaprompt -> plan -> delegation -> aggregation -> budgets.

Hybrid autonomy (PLAN.md 5.1): the LLM generates a plan from a fixed step
registry, validated by Pydantic; roles are fixed, sequence and iteration count
are dynamic. Every decision is logged. Triple budget guard: max plan steps,
token UsageLimits, wall-clock timeout with graceful degradation.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent

from mito_harness.logging_events import EventBus
from mito_harness.schemas import (
    PlanStep,
    ResearchPlan,
    RunResult,
    SourceKind,
    StepKind,
    StudyRecord,
    UnifiedRecord,
)
from setting import Settings, get_settings

logger = logging.getLogger(__name__)

MIN_RECORDS_BEFORE_REPLAN = 5

METAPROMPT = """\
You are the root orchestrator of a mitochondrial-medicine research harness.

Given a research query, produce a ResearchPlan as a sequence of steps chosen
ONLY from this registry (fixed roles, dynamic sequence):

- search: find publications/trial registrations (PubMed, Europe PMC, ClinicalTrials.gov)
- extract: turn fetched records into structured StudyRecords (drug, target, disease,
  phase, n, outcomes, effect direction)
- compare: build the mito-therapy vs standard-of-care comparison matrix
- evaluate: score the promise of each direction (skills/prospects_criteria)
- visualize: render the effect-direction plot, prospects ranking and gap map
- report: assemble the Russian-language mini-review with verified references
- review: verify citations/numbers and either approve or send back for fixes

Planning rules:
1. The first step MUST be 'search', the last meaningful step MUST be 'report'
   (a 'review' step before it is strongly recommended).
2. Every step needs a short human-readable description of WHAT it covers
   (e.g. which diseases/interventions).
3. Do not repeat the same step kind more than twice except 'search'/'extract'
   when the goal covers several diseases.
4. Total steps must stay small and focused; the harness enforces a hard cap.
5. params may carry 'diseases'/'interventions' lists to focus a step.

Your plan is executed by code: agents, tools and skills are wired per step kind.
"""


@dataclass
class RunState:
    """Mutable state accumulated across plan steps of one run."""

    goal: str
    query_id: str
    records: list[UnifiedRecord] = field(default_factory=list)
    studies: list[StudyRecord] = field(default_factory=list)
    comparison: dict[str, Any] = field(default_factory=dict)
    prospects: dict[str, Any] = field(default_factory=dict)
    plots: list[str] = field(default_factory=list)
    plot_titles: dict[str, str] = field(default_factory=dict)
    report_markdown: str = ""
    review: dict[str, Any] = field(default_factory=dict)
    replanned: bool = False


StepHandler = Callable[[RunState, PlanStep], Awaitable[None]]


def default_handlers() -> dict[StepKind, StepHandler | None]:
    return {kind: None for kind in StepKind}


class Orchestrator:
    def __init__(
        self,
        settings: Settings | None = None,
        bus: EventBus | None = None,
        plan_model: Any = None,
        handlers: dict[StepKind, StepHandler | None] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.bus: EventBus = (
            bus
            if bus is not None
            else EventBus(
                run_id="unwired", outputs_dir=self.settings.paths.outputs_dir, console_format="{ts} [{event}]"
            )
        )
        self.plan_model = plan_model
        self.handlers: dict[StepKind, StepHandler | None] = default_handlers()
        if handlers:
            self.handlers.update(handlers)
        self.planner: Agent[Any, ResearchPlan] | None = None
        if plan_model is not None:
            self.planner = Agent(plan_model, output_type=ResearchPlan, instructions=METAPROMPT)

    def on(self, kind: StepKind, handler: StepHandler) -> None:
        self.handlers[kind] = handler

    async def run_query(self, query_id: str, goal: str) -> RunResult:
        self.bus.emit("run_started", payload={"query_id": query_id, "goal": goal[:160]})
        state = RunState(goal=goal, query_id=query_id)
        status = "ok"
        try:
            plan = await self._build_plan(goal)
            self.bus.emit(
                "plan_created",
                payload={"goal": goal[:160], "steps": [f"{s.id}:{s.kind.value}" for s in plan.steps]},
            )
            try:
                status = await self._execute_plan(plan, state)
            except TimeoutError:
                self.bus.emit("budget_degraded", payload={"reason": "wall_clock_timeout"})
                status = "degraded"
        except Exception as exc:
            logger.exception("run failed")
            self.bus.emit("task_failed", agent="orchestrator", payload={"error": str(exc)[:300]})
            status = "failed"

        result = RunResult(
            run_id=self.bus.run_id,
            query_id=query_id,
            status=status,
            plan=plan,
            records=state.studies,
            report_path=None,
            plots=state.plots,
        )
        self.bus.emit(
            "run_finished",
            payload={"status": status, "records": len(state.studies), "plots": len(state.plots)},
        )
        return result

    async def _build_plan(self, goal: str) -> ResearchPlan:
        assert self.planner is not None, "plan model not configured"
        s = self.settings
        scope = {
            "diseases": [d["name"] for d in self._diseases()],
            "interventions": [i["label"] for i in self._interventions()],
            "window": [self._window()["from_year"], self._window()["to_year"]],
        }
        prompt = f"Research query: {goal}\n\nFixed domain scope: {scope}\nHard step cap: {s.limits.max_plan_steps}."
        plan = await self.planner.run(prompt)
        return self._validate_plan(plan.output)

    def _validate_plan(self, plan: ResearchPlan) -> ResearchPlan:
        s = self.settings
        if len(plan.steps) > s.limits.max_plan_steps:
            plan = plan.model_copy(update={"steps": plan.steps[: s.limits.max_plan_steps]})
        kinds = [step.kind for step in plan.steps]
        if not kinds or kinds[0] != StepKind.search:
            plan.steps.insert(0, PlanStep(id="s0", kind=StepKind.search, description="initial literature search"))
        if StepKind.extract not in kinds:
            last_search = max((i for i, s in enumerate(plan.steps) if s.kind is StepKind.search), default=0)
            plan.steps.insert(
                last_search + 1,
                PlanStep(
                    id=f"sx{last_search}",
                    kind=StepKind.extract,
                    description="structured extraction of fetched records",
                ),
            )
        if StepKind.report not in kinds:
            plan.steps.append(PlanStep(id=f"s{len(plan.steps)}", kind=StepKind.report, description="final mini-review"))
        review_steps = [s for s in plan.steps if s.kind is StepKind.review]
        if not review_steps:
            plan.steps.append(
                PlanStep(id=f"sr{len(plan.steps)}", kind=StepKind.review, description="citation and claims validation")
            )
        else:
            report_idx = max(i for i, s in enumerate(plan.steps) if s.kind is StepKind.report)
            for step in review_steps:
                plan.steps.remove(step)
            for offset, step in enumerate(review_steps):
                plan.steps.insert(report_idx + 1 + offset, step)
        seen: set[str] = set()
        for idx, step in enumerate(plan.steps):
            if not step.id or step.id in seen:
                step.id = f"s{idx}"
            seen.add(step.id)
        return plan

    async def _execute_plan(self, plan: ResearchPlan, state: RunState) -> str:
        timeout = self.settings.limits.wall_clock_minutes * 60
        async with asyncio.timeout(timeout):
            for step in plan.steps:
                self.bus.emit("plan_step_started", step_id=step.id, payload={"kind": step.kind.value})
                handler = self.handlers.get(step.kind)
                if handler is None:
                    self.bus.emit(
                        "task_skipped", step_id=step.id, agent=step.kind.value, payload={"reason": "no handler wired"}
                    )
                    continue
                await handler(state, step)
                self.bus.emit(
                    "plan_step_finished",
                    step_id=step.id,
                    payload={
                        "kind": step.kind.value,
                        "records": len(state.records),
                        "studies": len(state.studies),
                    },
                )
                if step.kind is StepKind.search and not state.replanned:
                    await self._maybe_replan(state)
        return "ok"

    async def _maybe_replan(self, state: RunState) -> None:
        if len(state.records) >= MIN_RECORDS_BEFORE_REPLAN:
            return
        state.replanned = True
        interventions = [i["label"] for i in self._interventions()]
        self.bus.emit(
            "plan_adjusted",
            payload={
                "reason": f"sparse results ({len(state.records)} records)",
                "action": "broadened search with synonym expansion",
            },
        )
        synonyms = {
            "elamipretide (SS-31)": "elamipretide OR SS-31 OR MTP-31 OR Bendavia",
            "LHON gene therapy (rAAV2/2-ND4)": "lenadogene nolparvovec OR rAAV2-ND4 OR ND4 gene therapy",
            "NAD+ precursors (NR/NMN)": "nicotinamide riboside OR NMN OR NAD precursor",
        }
        extra_terms = [synonyms.get(label, label) for label in interventions[:3]]
        query = " OR ".join(f"({t})" for t in extra_terms)
        search_handler = self.handlers.get(StepKind.search)
        if search_handler is not None:
            broadened = PlanStep(
                id="replan-search",
                kind=StepKind.search,
                description="broadened synonym search after sparse results",
                params={"forced_terms": query, "sources": [SourceKind.pubmed.value, SourceKind.europepmc.value]},
            )
            await search_handler(state, broadened)

    def _diseases(self) -> list[dict[str, Any]]:
        return list(self.settings.queries_config.get("diseases", []))

    def _interventions(self) -> list[dict[str, Any]]:
        return list(self.settings.queries_config.get("mito_interventions", []))

    def _window(self) -> dict[str, Any]:
        return dict(self.settings.queries_config.get("window", {"from_year": 2021, "to_year": 2026}))
