# V0 execution capability — owner amendment, 2026-09-05

The owner explicitly narrowed platform coverage after independent review
demonstrated detached descendants surviving native macOS process-group cleanup.
This amends section 23 of the supplied implementation plan, preserving section
16's cleanup requirement. It does not change the Muse experiment boundary.

Candidate execution is permitted only when the active backend guarantees that
every process attributable to the candidate is terminated before the attempt
becomes terminal. Process-group membership alone is insufficient because
descendants may detach or reparent. Accepted execution requires semantic and
artifact/result success plus confirmed containment cleanup.

Ubuntu and Windows require full execution, detached-descendant teardown,
interruption recovery and exact portable receipt/report agreement. macOS
requires parsing, candidate/profile validation, identity, persistence, replay,
receipt/report, tamper, packaging and deterministic-format qualification.
Fresh macOS execution must fail closed with EXECUTION_CONTAINMENT_UNAVAILABLE,
with no acceptance receipt and no candidate process started.

**Independent Application Acceptance V0 does not support native candidate
execution on unprivileged macOS.** An independently proven containment backend
could later add that capability; no container or VM backend is required by V0.

Identities and portable formats remain platform-independent. The original 19
portable non-claims and profile bytes remain frozen; this additional explicit
platform non-claim is recorded here and in doctor execution-capability facts.
Original Muse snapshots and scores remain unchanged. Source execution tests
now skip unsupported platforms under this owner amendment; separate tests
prove macOS refusal, zero candidate processes and receipt withholding.
