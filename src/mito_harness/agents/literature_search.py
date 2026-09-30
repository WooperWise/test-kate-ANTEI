"""LiteratureSearchAgent: plans atomic queries per source, orchestrator executes them.

The agent translates the research goal + domain scope into a set of concrete
search queries (source, terms, disease, intervention). Query EXECUTION happens
in the orchestrator so every tool call is logged and deduplicated centrally.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from mito_harness.schemas import SearchPlan

SEARCH_PLANNER_INSTRUCTIONS = """\
You are the literature-search planner of a mitochondrial-medicine research harness.

Translate the research goal into 6-12 atomic search queries covering:
- each relevant disease x intervention combination mentioned in the goal;
- each of the three sources: 'pubmed' (journal literature), 'europepmc' (journal
  literature incl. preprints), 'ctgov' (trial registrations, query.term syntax).

Query rules:
- terms: short boolean expressions, e.g. (elamipretide OR SS-31 OR MTP-131) AND "heart failure"
- use MeSH-friendly phrasing for pubmed/europepmc; plain keywords for ctgov;
- do NOT include year filters in terms (the orchestrator applies the window);
- disease/intervention fields carry the semantic tag for later grouping.

Your output is a SearchPlan consumed by code, not prose.
"""


def build_search_planner(model: Any) -> Agent[Any, SearchPlan]:
    return Agent(model, output_type=SearchPlan, instructions=SEARCH_PLANNER_INSTRUCTIONS)


def search_prompt(goal: str, window_from: int, window_to: int, max_results: int, scope: str) -> str:
    return (
        f"Research goal: {goal}\n\n"
        f"Publication window: {window_from}-{window_to} (applied automatically, do not add to terms).\n"
        f"Max records budget: {max_results} after deduplication - plan accordingly.\n\n"
        f"Domain scope: {scope}"
    )
