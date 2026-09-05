# Independent Application Acceptance V0 evidence

Product qualification and the Muse contributor experiment are separate outcomes.
The original implementation plan and owner platform amendment are bound by
[PLAN.md](PLAN.md); repository bootstrap facts are in [BASELINE.json](BASELINE.json).

The product evidence consists of QUALIFICATION.json and per-platform receipts,
three primary journey records, copied journey input/document bytes, identity
vectors, ORACLE-VALID.json, the 26-control ORACLE-TAMPER-MATRIX.json, exact package
identity, independent reviews and the closure record. These final files are
prepared after successful platform qualification; their status is never inferred
from an original Muse hidden score.

[ORACLE.py](ORACLE.py) and its three adjacent JSON sidecars are an exact standalone
copy of product oracle revision 2. It validates copied candidate, profile,
receipt/report and expected release identity bytes without importing the product.
[ORACLE-DEFECT-ADJUDICATION.md](ORACLE-DEFECT-ADJUDICATION.md) distinguishes
Astra-authored oracle corrections from matching product-source repairs. The
[original hidden oracle](oracle-original/) is immutable historical evidence.

[Developer provenance](../../tests/fixtures/product/DEVELOPER-PROVENANCE.json)
records actual Developer0.4.0 PASSED/VERIFIED exports for all three primary
journeys. Later malformed and semantic controls are resealed synthetic controls;
they do not claim additional Developer verifications.

The final [Muse assessment](MUSE-CONTRIBUTOR-EVALUATION.json) is
`high_review_burden`. [Attribution](MUSE-ATTRIBUTION-DIFF.json) measures retained
source and separately identifies Astra replacement backend code.
[Interventions](ASTRA-INTERVENTIONS.json) preserve the sole feedback packet and
post-Muse repairs. [MUSE-EVIDENCE-INDEX.json](MUSE-EVIDENCE-INDEX.json) maps every
required logical run deliverable to its exact preserved path and hash. Full
exports containing encrypted private reasoning remain local; published provenance
and visible trajectories disclose export hashes, omissions and reported usage.

[REVIEWS.md](REVIEWS.md) records independent Reviews A–E and superseded findings.
The repository retains failed attempts and their causal repairs. No package
registry publication, runtime installation, binding, deployment or general model
benchmark claim follows from this campaign.
