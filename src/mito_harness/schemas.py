"""Core Pydantic schemas shared across the harness.

Step-2 scope: unified record model (post-parse, pre-LLM), plotting data
models with the honesty contract, citation verification result.
Step-3 extends this module with LLM-extraction output schemas.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SourceKind(str, Enum):
    pubmed = "pubmed"
    europepmc = "europepmc"
    ctgov = "ctgov"


class UnifiedRecord(BaseModel):
    """Normalized record from any source; LLM extraction input (never model memory)."""

    source: SourceKind
    title: str
    abstract: str | None = None
    journal: str | None = None
    year: int | None = None
    pmid: str | None = None
    doi: str | None = None
    nct_id: str | None = None
    pubtypes: list[str] = Field(default_factory=list)
    trial_phase: str | None = None
    enrollment: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @property
    def ref_id(self) -> str:
        return self.nct_id or self.pmid or self.doi or "no-id"


class Direction(str, Enum):
    positive = "positive"
    negative = "negative"
    neutral = "neutral"
    unclear = "unclear"


class EvidenceLevel(str, Enum):
    meta = "meta"  # systematic review / meta-analysis
    rct = "rct"
    observational = "observational"
    preclinical = "preclinical"


class DirectionPlotItem(BaseModel):
    """One marker = one study/arm/outcome. No cross-study averaging, ever."""

    study_label: str
    outcome: str
    arm: str  # 'mito' or 'standard'
    direction: Direction
    significant: bool = False
    evidence: EvidenceLevel
    ref_id: str  # PMID or NCT id shown on the plot


class ProspectsComponent(BaseModel):
    name: str
    score: float = Field(ge=0, le=10)
    weight: float = Field(gt=0, le=1)


class ProspectsItem(BaseModel):
    label: str
    total: float = Field(ge=0, le=10)
    components: list[ProspectsComponent]
    rationale: str = ""


class GapCell(BaseModel):
    intervention: str
    disease: str
    n_studies: int = 0
    top_evidence: EvidenceLevel | None = None
    refs: list[str] = Field(default_factory=list)


class VerifyResult(BaseModel):
    identifier: str
    claimed_title: str
    fetched_title: str | None = None
    verified: bool = False
    title_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    year_claimed: int | None = None
    year_fetched: int | None = None
    reason: str = ""


class SearchQuery(BaseModel):
    """Atomic search task produced by the literature-search agent."""

    source: SourceKind
    terms: str
    disease: str | None = None
    intervention: str | None = None


class StudyPhase(str, Enum):
    preclinical = "preclinical"
    early_phase1 = "early_phase1"
    phase1 = "phase1"
    phase2 = "phase2"
    phase3 = "phase3"
    phase4 = "phase4"
    not_applicable = "not_applicable"


class OutcomeMeasure(BaseModel):
    """One measured outcome within a study; direction relative to comparator."""

    name: str
    direction: Direction
    significant: bool = False
    effect_text: str = ""  # verbatim effect description from the abstract
    favors: str | None = None  # 'intervention' | 'comparator' | None


class StudyRecord(BaseModel):
    """Structured extraction target for the DataExtractor agent (strict)."""

    ref_id: str
    title: str
    source: SourceKind
    intervention: str
    intervention_class: str = ""
    target: str | None = None
    disease: str
    is_standard_of_care: bool = False
    design: str
    phase: StudyPhase
    n_participants: int | None = Field(default=None, ge=0)
    outcomes: list[OutcomeMeasure] = Field(min_length=1)
    evidence_level: EvidenceLevel
    year: int | None = None


class StepKind(str, Enum):
    search = "search"
    extract = "extract"
    compare = "compare"
    evaluate = "evaluate"
    visualize = "visualize"
    report = "report"
    review = "review"


class PlanStep(BaseModel):
    id: str
    kind: StepKind
    description: str
    params: dict[str, Any] = Field(default_factory=dict)


class ResearchPlan(BaseModel):
    """LLM-generated plan validated against the step registry (hybrid autonomy)."""

    goal: str
    steps: list[PlanStep] = Field(min_length=3)

    def step_ids(self) -> list[str]:
        return [s.id for s in self.steps]


class SearchPlan(BaseModel):
    """LiteratureSearchAgent output: atomic queries to execute in parallel."""

    queries: list[SearchQuery] = Field(min_length=1)


class RunResult(BaseModel):
    run_id: str
    query_id: str
    status: str  # 'ok' | 'degraded' | 'failed'
    plan: ResearchPlan
    records: list[StudyRecord] = Field(default_factory=list)
    report_path: str | None = None
    plots: list[str] = Field(default_factory=list)


class ComparisonResult(BaseModel):
    """ComparativeAnalyst output: honest direction matrix + gap map data."""

    plot_items: list[DirectionPlotItem] = Field(min_length=1)
    gap_cells: list[GapCell] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)


class ProspectsAssessment(BaseModel):
    """ProspectsEvaluator output: weighted scoring with visible components."""

    items: list[ProspectsItem] = Field(min_length=1)
    leaders: list[str] = Field(default_factory=list)
    outsiders: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class VisualizationSpec(BaseModel):
    """VisualizerAgent output: chart titles/captions (rendering is deterministic)."""

    direction_plot_title: str
    ranking_title: str
    gapmap_title: str


class ReviewFinding(BaseModel):
    location: str
    issue: str
    action: str  # FIX | REMOVE | VERIFY
    ref_id: str | None = None


class ReviewVerdict(BaseModel):
    approved: bool
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)


class ReportNarrative(BaseModel):
    """ReporterAgent output: Russian-language narrative blocks."""

    summary: list[str] = Field(min_length=1)
    methods_notes: list[str] = Field(default_factory=list)
    directions_analysis: list[str] = Field(default_factory=list)
    outsiders_analysis: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(min_length=1)
