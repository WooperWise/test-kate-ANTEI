---
id: prospects_criteria
description: Transparent weighted rubric for scoring the promise of mitochondria-directed therapy directions. Load before scoring or ranking directions.
---

# Prospects rubric (weights live HERE, not in code)

Score every direction (intervention x disease) on five components, each 0-10,
then compute the weighted total. Component scores must cite at least one ref_id.

| Component | Weight | What 0 means | What 10 means |
|---|---|---|---|
| evidence_quality | 0.30 | only preclinical, weak effects | positive RCT(s)/meta on patient-important outcomes |
| effect_direction | 0.25 | neutral or harmful signals | consistent benefit across outcomes and studies |
| pipeline_momentum | 0.15 | no active trials 2021-2026 | ongoing phase 2/3 with posted results |
| unmet_need | 0.15 | good standard therapy exists | no disease-modifying standard at all |
| translatability | 0.15 | delivery/safety unresolved (mtDNA) | oral/small molecule, safety established |

Rules:
1. total = sum(score * weight), rounded to 1 decimal; report components alongside.
2. Negative RCT evidence (benefit failed to replicate in phase 3) caps
   effect_direction at 3 and must be named in the rationale.
3. Registry-only evidence (no posted results) may raise pipeline_momentum but
   NEVER evidence_quality or effect_direction.
4. Directions with fewer than 2 distinct ref_ids overall: cap total at 4 and
   flag "thin evidence base".
5. The top-scoring direction is a leader only if total >= 6; otherwise report
   "no convincing leaders yet". Outsiders = bottom quartile with explicit reasons.
6. Rationale strings must reference ref_ids (PMID/NCT) for every claim.
