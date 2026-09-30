---
id: citation_checklist
description: Checklist for validating citations, numbers and claims in the report draft before approval. Load before reviewing or approving any report.
---

# Citation & claim validation checklist

For EVERY sentence in the report draft that contains a number, an effect claim,
or a reference id, verify:

1. **Identifier exists**: PMID/NCT/DOI resolves (call verify_citation; do not trust memory).
2. **Title match**: fetched title clearly describes the same study as claimed.
3. **Number provenance**: every dosage, n, effect size and p-value appears in the
   source record data you were given. Flag numbers with no provenance as REMOVE.
4. **No invention**: no study, author, trial name or result outside the provided
   StudyRecords may appear in the report.
5. **Direction fidelity**: the claimed benefit/harm direction matches the extracted
   direction of that outcome.
6. **Phase fidelity**: the phase in the narrative matches the extracted phase
   (do not upgrade phase 2 to phase 3).
7. **Standard-of-care honesty**: statements about standard therapy must match the
   configured standard_of_care; no invented guidelines.

Verdict rules:
- `approved` only when zero blocking findings remain.
- Each blocking finding: `{location, issue, action}` where action is one of
  FIX (specific correction), REMOVE (delete the claim), VERIFY (re-run tool).
- If the same claim fails twice, action is REMOVE: it disappears from the report
  into the "Rejected by reviewer" section with the reason.
