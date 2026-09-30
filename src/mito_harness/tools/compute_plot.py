"""compute_plot: deterministic sandbox for calculations and honest matplotlib PNGs.

Honesty contract (PLAN.md section 8), enforced here so no caller can bypass it:
  1. one marker = one study/registration, never a cross-study average;
  2. only effect DIRECTION is encoded (+/-/0), phase goes into the label;
  3. color = evidence level;
  4. every marker is annotated with its PMID/NCT ref;
  5. footer disclaimer: research tool, not medical advice.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless sandbox

import matplotlib.pyplot as plt  # noqa: E402

from mito_harness.schemas import (  # noqa: E402
    Direction,
    DirectionPlotItem,
    EvidenceLevel,
    GapCell,
    ProspectsItem,
)

DISCLAIMER = "Research tool, not medical advice. Markers show effect direction only; no cross-study averaging."

_EVIDENCE_COLORS: dict[EvidenceLevel, str] = {
    EvidenceLevel.meta: "#1a9850",
    EvidenceLevel.rct: "#66bd63",
    EvidenceLevel.observational: "#fdae61",
    EvidenceLevel.preclinical: "#d73027",
}

_DIRECTION_MARKERS: dict[Direction, str] = {
    Direction.positive: "+",
    Direction.negative: "_",
    Direction.neutral: "o",
    Direction.unclear: "$?$",
}

_ARM_OFFSET = {"mito": -0.18, "standard": 0.18}


def effect_direction_plot(items: list[DirectionPlotItem], path: Path, title: str) -> Path:
    """Effect-direction plot: rows = outcomes, columns = studies; mito vs standard."""
    outcomes = sorted({i.outcome for i in items})
    studies = sorted({i.study_label for i in items})
    y_pos = {o: idx for idx, o in enumerate(outcomes)}
    x_pos = {s: idx for idx, s in enumerate(studies)}

    fig, ax = plt.subplots(figsize=(1.2 * max(len(studies), 4) + 3, 0.6 * max(len(outcomes), 4) + 2.5))
    seen_refs: set[str] = set()

    for item in items:
        x = x_pos[item.study_label] + _ARM_OFFSET.get(item.arm, 0.0)
        y = y_pos[item.outcome]
        marker = _DIRECTION_MARKERS[item.direction]
        color = _EVIDENCE_COLORS[item.evidence]
        size = 220 if item.significant else 90
        ax.scatter(
            x,
            y,
            s=size,
            marker=marker,
            c=color,
            edgecolors="none" if marker in {"+", "_"} else "black",
            linewidths=0.6,
            zorder=3,
        )
        if item.ref_id not in seen_refs:
            seen_refs.add(item.ref_id)
            ax.annotate(
                item.ref_id,
                (x, y),
                xytext=(0, -14),
                textcoords="offset points",
                ha="center",
                fontsize=6.5,
                rotation=45,
                color="dimgray",
            )

    ax.set_xticks(range(len(studies)))
    ax.set_xticklabels(studies, rotation=30, ha="right", fontsize=8)
    ax.set_yticks(range(len(outcomes)))
    ax.set_yticklabels(outcomes, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Study / trial (phase in label)")
    ax.set_title(title, fontsize=11)
    ax.grid(axis="y", alpha=0.3, zorder=0)

    handles = [
        plt.Line2D(
            [0], [0], marker="o", color="w", markerfacecolor=c, markeredgecolor="black", label=level.value, markersize=9
        )
        for level, c in _EVIDENCE_COLORS.items()
    ]
    ax.legend(handles=handles, title="Evidence level", loc="upper right", fontsize=7, title_fontsize=8)
    fig.text(0.01, 0.005, DISCLAIMER, fontsize=6.5, color="gray", style="italic")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def prospects_ranking(items: list[ProspectsItem], path: Path, title: str) -> Path:
    """Horizontal stacked bars: prospect score split into transparent components."""
    items = sorted(items, key=lambda i: i.total)
    labels = [i.label for i in items]
    fig, ax = plt.subplots(figsize=(9, 0.7 * max(len(items), 3) + 2))
    component_names: list[str] = []
    for item in items:
        for comp in item.components:
            if comp.name not in component_names:
                component_names.append(comp.name)

    colormap = plt.colormaps.get_cmap("tab20")
    left = [0.0] * len(items)
    for ci, comp_name in enumerate(component_names):
        widths = []
        for item in items:
            matched = next((c for c in item.components if c.name == comp_name), None)
            widths.append(matched.score * matched.weight if matched else 0.0)
        ax.barh(labels, widths, left=left, color=colormap(ci % 20), edgecolor="white", label=comp_name)
        left = [prev + w for prev, w in zip(left, widths, strict=False)]

    for idx, item in enumerate(items):
        ax.text(left[idx] + 0.08, idx, f"{item.total:.1f}", va="center", fontsize=9, fontweight="bold")

    ax.set_xlabel("Weighted prospect score (0-10); weights defined in skills/prospects_criteria")
    ax.set_title(title, fontsize=11)
    ax.set_xlim(0, max(left) * 1.12 if left else 1)
    ax.legend(fontsize=7, loc="lower right", ncol=min(3, max(len(component_names), 1)))
    fig.text(0.01, 0.005, DISCLAIMER, fontsize=6.5, color="gray", style="italic")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def evidence_gap_map(cells: list[GapCell], path: Path, title: str) -> Path:
    """Intervention x disease matrix colored by evidence density/top level."""
    interventions = sorted({c.intervention for c in cells})
    diseases = sorted({c.disease for c in cells})
    level_rank = {
        None: 0,
        EvidenceLevel.preclinical: 1,
        EvidenceLevel.observational: 2,
        EvidenceLevel.rct: 3,
        EvidenceLevel.meta: 4,
    }
    rank_color = ["#f5f5f5", "#fddbc7", "#f4a582", "#d6604d", "#b2182b"]

    by_cell = {(c.intervention, c.disease): c for c in cells}
    fig, ax = plt.subplots(figsize=(0.2 + 1.6 * max(len(diseases), 1), 0.2 + 0.7 * max(len(interventions), 1) + 2))
    for yi, intervention in enumerate(interventions):
        for xi, disease in enumerate(diseases):
            cell = by_cell.get((intervention, disease))
            rank = level_rank[cell.top_evidence] if cell else 0
            ax.add_patch(plt.Rectangle((xi, yi), 1, 1, facecolor=rank_color[rank], edgecolor="white"))
            if cell and cell.n_studies:
                ax.text(
                    xi + 0.5,
                    yi + 0.5,
                    f"{cell.n_studies}\n{cell.top_evidence.value if cell.top_evidence else ''}",
                    ha="center",
                    va="center",
                    fontsize=8,
                )

    ax.set_xlim(0, len(diseases))
    ax.set_ylim(0, len(interventions))
    ax.set_xticks([i + 0.5 for i in range(len(diseases))])
    ax.set_xticklabels(diseases, fontsize=8, rotation=20, ha="right")
    ax.set_yticks([i + 0.5 for i in range(len(interventions))])
    ax.set_yticklabels(interventions, fontsize=8)
    ax.invert_yaxis()
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=11)
    handles = [
        plt.Line2D(
            [0],
            [0],
            marker="s",
            color="w",
            markerfacecolor=rank_color[r],
            markeredgecolor="gray",
            markersize=10,
            label=name,
        )
        for r, name in enumerate(["no evidence", "preclinical", "observational", "RCT", "meta"])
    ]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.02, 1), fontsize=7, title="top evidence")
    fig.text(0.01, 0.005, DISCLAIMER, fontsize=6.5, color="gray", style="italic")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path
