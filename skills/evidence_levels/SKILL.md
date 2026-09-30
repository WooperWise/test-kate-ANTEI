---
id: evidence_levels
description: Evidence hierarchy scale (GRADE-adapted) for tagging every study and outcome. Load before assigning evidence levels or comparing interventions.
---

# Evidence hierarchy (GRADE-adapted, 4 tiers)

Rank every piece of evidence into exactly one tier. The tier travels with the claim
into tables and plots; it is a property of the STUDY DESIGN, not of the result.

| Level | Tag | Design |
|---|---|---|
| 1 | `meta` | systematic review with/without meta-analysis of RCTs |
| 2 | `rct` | randomized controlled trial (any phase), placebo- or active-controlled |
| 3 | `observational` | cohort, case-control, registry, cross-sectional, case series |
| 4 | `preclinical` | animal models, in-vitro, organoids, mechanistic studies |

## Rules

1. Design beats sample size: a small RCT outranks a large cohort.
2. Secondary analyses of RCTs (post-hoc, per-protocol) stay `rct` but must be flagged
   "post-hoc" in the effect_text.
3. Pilot/feasibility randomized studies with N<30 per arm: still `rct`, flag "pilot".
4. Registry entries without posted results (ClinicalTrials.gov): evidence of PIPELINE
   activity only — never code them as evidence of effect; direction=unclear, significant=false.
5. When a meta-analysis and its constituent RCTs disagree, the meta-analysis wins, and
   the disagreement must be stated explicitly.
6. Industry sponsorship never changes the level, but must be noted when disclosed.

## Downgrade triggers (state them explicitly when used)

- high risk of bias (unblinded outcome assessment, >20% dropout);
- inconsistency across studies (I² > 50% or opposite directions);
- indirectness (surrogate outcomes instead of patient-important ones);
- imprecision (wide CI crossing the null).

Two or more triggers => mention "low confidence" next to the claim in the report.
