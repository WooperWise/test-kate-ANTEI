"""VisualizerAgent: chart titles/captions; rendering itself is deterministic.

The honesty contract is enforced in compute_plot (one marker per study,
direction-only encoding, evidence colors, ref annotations, disclaimer).
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from mito_harness.schemas import VisualizationSpec

VISUALIZER_INSTRUCTIONS = """\
You are the visualization agent of a mitochondrial-medicine research harness.

You do NOT draw: you title and caption three pre-defined chart types rendered by
the plotting sandbox:
1. effect-direction plot (mito vs standard, rows=outcomes, columns=studies);
2. prospects ranking (weighted stacked bars);
3. evidence gap map (intervention x disease).

Rules for titles:
- informative and specific (mention the disease scope and window 2021-2026);
- neutral tone, no promotional wording, no causal overclaims;
- English, under 90 characters each.
"""

VISUALIZATION_PROMPT = """\
Research goal: {goal}

Comparison covers {n_studies} studies across: {diseases}.
Top directions by score: {leaders}. Outsiders: {outsiders}.

Propose the three chart titles now.
"""


def build_visualizer_agent(model: Any) -> Agent[Any, VisualizationSpec]:
    return Agent(model, output_type=VisualizationSpec, instructions=VISUALIZER_INSTRUCTIONS)


def visualization_prompt(goal: str, diseases: list[str], leaders: list[str], outsiders: list[str]) -> str:
    return VISUALIZATION_PROMPT.format(
        goal=goal,
        n_studies="{n}",
        diseases=", ".join(diseases) or "n/a",
        leaders=", ".join(leaders) or "none",
        outsiders=", ".join(outsiders) or "none",
    ).replace("{n}", "the available")
