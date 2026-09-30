---
id: extraction_rules
description: Rules for extracting trial data (drug, target, disease, phase, n, outcomes, effect) from PubMed/registries abstracts. Load before extracting any study record.
---

# Extraction rules for clinical/preclinical evidence

You are extracting structured data from ONE abstract/registration. The abstract text is
your ONLY source of truth. If a field is not stated in the text, leave it empty or mark
as unclear — NEVER fill it from your prior knowledge.

## Mandatory rules

1. `ref_id`: copy the identifier exactly as provided (PMID or NCT id). Never invent one.
2. `intervention`: the experimental mitochondria-targeted drug OR the standard-of-care
   comparator being evaluated. Set `is_standard_of_care=true` only for the comparator arm drug.
3. `disease`: the studied condition, normalized to one of: primary mitochondrial diseases,
   Leber hereditary optic neuropathy, chronic heart failure, Parkinson's disease.
4. `phase`: map text to the closest of preclinical / early_phase1 / phase1 / phase2 /
   phase3 / phase4 / not_applicable. Registry "PHASE2" = phase2. Animal or in-vitro = preclinical.
5. `n_participants`: only the number randomized or enrolled, if stated. Animal study N goes here too.
6. `outcomes` (at least one): each measured outcome with:
   - `name`: the outcome as named in the text (e.g. "6-minute walk distance", "BCVA", "VO2 peak");
   - `direction`: positive (benefit for the intervention arm), negative (harm/worsening),
     neutral (no significant difference), unclear (cannot be determined);
   - `significant`: true only if the text reports p<0.05 or an explicit significant finding;
   - `effect_text`: SHORT verbatim quote of the effect (e.g. "+25 m (p=0.03)");
   - `favors`: 'intervention', 'comparator' or null.
7. `evidence_level`: meta / rct / observational / preclinical following the study design
   (see the evidence_levels skill for the full scale).
8. `year`: publication year (PubMed) or study start year (registry).

## Common pitfalls

- Distinguish the DRUG arm from the STANDARD arm: extract separate records if both are reported.
- "Significant improvement in secondary outcome" without a number → significant=true,
  effect_text="improved (secondary outcome)", direction=positive.
- Abstracts of reviews/meta-analyses: extract as design="meta-analysis", evidence_level=meta,
  outcomes = the pooled findings, n_participants = pooled N if stated.
- Do NOT extract background/mechanism sentences as outcomes.
