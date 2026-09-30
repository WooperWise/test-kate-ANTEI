"""ReporterAgent (narrative) + deterministic markdown assembly of the mini-review.

Numbers, tables and reference lists never pass through the LLM again: the
reporter only writes narrative blocks (Russian); assembly is deterministic.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from mito_harness.schemas import ReportNarrative, ReviewVerdict

REPORTER_INSTRUCTIONS = """\
You are the reporter of a mitochondrial-medicine research harness.

Write the narrative blocks of a Russian-language mini-review STRICTLY from the
structured evidence provided. You never invent numbers, studies or references:
if a fact is not in the data, do not state it. Keep the scientific register,
use "можно предположить/данные указывают" hedging where evidence is thin.

Blocks (all in Russian):
- summary: 3-5 ключевых выводов, каждый с ref_id в скобках;
- methods_notes: как Harness проводил поиск (источники, окно, критерии);
- directions_analysis: разбор наиболее перспективных направлений со ссылками на
  компоненты скоринга и ref_id;
- outsiders_analysis: почему аутсайдеры проигрывают (негативные RCT, дефицит
  данных), с ref_id;
- limitations: честные ограничения экспресс-обзора.
"""

REPORT_PROMPT = """\
Research goal: {goal}

--- COMPARISON INSIGHTS ---
{insights}

--- PROSPECTS SCORES (leaders: {leaders}; outsiders: {outsiders}) ---
{prospects_digest}

--- STUDY RECORDS DIGEST ---
{records_digest}

Write the Russian narrative blocks now. Every factual sentence ends with its ref_id(s).
"""


def build_reporter_agent(model: Any) -> Agent[Any, ReportNarrative]:
    return Agent(model, output_type=ReportNarrative, instructions=REPORTER_INSTRUCTIONS)


def reporter_prompt(state: Any, corrections: str = "") -> str:
    records_digest = "\n".join(
        f"- {s.ref_id} [{s.evidence_level.value}/{s.phase.value}] {s.intervention} при {s.disease} "
        f"({s.design}, n={s.n_participants or '?'}) исходы: "
        + "; ".join(f"{o.name}={o.direction.value}{'*' if o.significant else ''}" for o in s.outcomes)
        for s in state.studies
    )
    prospects_digest = "\n".join(
        f"- {i.get('label')}: total={i.get('total')} components="
        + ",".join(f"{c.get('name')}={c.get('score')}" for c in i.get("components", []))
        + f" | {i.get('rationale', '')}"
        for i in state.prospects.get("items", [])
    )
    correction_block = (
        f"\n--- REVIEWER CORRECTIONS (mandatory, fix each item) ---\n{corrections}\n" if corrections else ""
    )
    return (
        REPORT_PROMPT.format(
            goal=state.goal,
            insights="\n".join(state.comparison.get("insights", [])) or "n/a",
            leaders=", ".join(state.prospects.get("leaders", [])) or "none",
            outsiders=", ".join(state.prospects.get("outsiders", [])) or "none",
            prospects_digest=prospects_digest or "n/a",
            records_digest=records_digest or "n/a",
        )
        + correction_block
    )


def assemble_markdown(state: Any, narrative: ReportNarrative, verdict: ReviewVerdict | None) -> str:
    """Deterministic assembly of the 8-section mini-review (PLAN.md section 12)."""
    lines: list[str] = ["# Мини-обзор: митохондриально-таргетная терапия vs стандарт лечения", ""]

    lines += ["## 1. Резюме", ""]
    lines += [f"- {item}" for item in narrative.summary]
    lines += [""]

    lines += [
        "## 2. Методы Harness",
        "",
        "- Источники: PubMed (E-utilities), Europe PMC (REST), ClinicalTrials.gov (API v2).",
        "- Окно публикаций/регистраций: 2021-2026; пул после дедупликации: "
        f"{len(state.records)} записей, структурировано {len(state.studies)}.",
    ]
    lines += [f"- {item}" for item in narrative.methods_notes]
    lines += [""]

    lines += ["## 3. Сравнительная матрица (митотерапия vs стандарт)", ""]
    lines += [
        "| ref_id | вмешательство | заболевание | фаза | доказательность | исходы (направление) |",
        "|---|---|---|---|---|---|",
    ]
    for s in state.studies:
        outcomes = "; ".join(f"{o.name}: {o.direction.value}{' (знач.)' if o.significant else ''}" for o in s.outcomes)
        lines.append(
            f"| {s.ref_id} | {s.intervention} | {s.disease} | {s.phase.value} | {s.evidence_level.value} | {outcomes} |"
        )
    lines += [""]

    lines += ["## 4. Наиболее перспективные направления", ""]
    lines += [f"- {item}" for item in narrative.directions_analysis]
    lines += ["", "**Скоринг направлений** (веса - в skills/prospects_criteria):", ""]
    lines += ["| направление | итог | компоненты |", "|---|---|---|"]
    for item in state.prospects.get("items", []):
        comps = ", ".join(f"{c.get('name')}={c.get('score')}" for c in item.get("components", []))
        lines.append(f"| {item.get('label')} | {item.get('total')} | {comps} |")
    lines += [""]

    lines += ["## 5. Аутсайдеры", ""]
    lines += [f"- {item}" for item in narrative.outsiders_analysis]
    lines += [""]

    lines += ["## 6. Ограничения", ""]
    lines += [f"- {item}" for item in narrative.limitations]
    lines += [
        "- Экспресс-обзор, а не систематический: без протокола PRISMA и мета-анализа.",
        "- Инструмент исследовательский, не является медицинской рекомендацией.",
        "",
    ]

    lines += ["## 7. Ссылки (верифицированы через re-fetch)", ""]
    for s in state.studies:
        source_url = (
            f"https://pubmed.ncbi.nlm.nih.gov/{s.ref_id}/"
            if s.ref_id.isdigit()
            else (
                f"https://clinicaltrials.gov/study/{s.ref_id}"
                if s.ref_id.startswith("NCT")
                else f"https://doi.org/{s.ref_id}"
            )
        )
        lines.append(f"- {s.ref_id}: {s.title} ({s.year or 'n/a'}) — {source_url}")
    lines += [""]

    if verdict is not None and verdict.findings:
        lines += ["## 8. Отклонено ревьюером", ""]
        lines.append(f"Вердикт: {'одобрено' if verdict.approved else 'одобрено после деэскалации'}. {verdict.summary}")
        lines += ["", "| место | проблема | действие | ref |", "|---|---|---|---|"]
        for f in verdict.findings:
            lines.append(f"| {f.location} | {f.issue} | {f.action} | {f.ref_id or '-'} |")
        lines += [""]
    else:
        lines += ["## 8. Отклонено ревьюером", "", "Претензий не зафиксировано.", ""]

    if state.plots:
        lines += ["## Приложение: визуализации", ""]
        for plot in state.plots:
            name = plot.rsplit("/", 1)[-1]
            lines.append(f"![{name}]({name})")
        lines += [""]

    return "\n".join(lines)
