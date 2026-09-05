# Independently validated release candidate V1

This validator is owned by the acceptor; it must not import capy_developer,
its validators, databases, caches, or source. The accepted public format is
represented by RELEASE-CANDIDATE-V1-EXAMPLE.json,
VERIFICATION-RECEIPT-V1-EXAMPLE.json and tests/fixtures/fixed-v1.capyrc.
Each schema-owned object has exactly the example's keys. Values vary where
specified below; unknown/missing fields fail. IDs, hashes, sizes and booleans
must retain their precise types; booleans cannot substitute for integers.

Outer ZIP: exactly RELEASE-CANDIDATE.json, application/application.zip,
application/interaction.json, evidence/verification.json,
toolchain/authoring-bundle.zip, in that order. Apply the same full-byte canonical
ZIP/JSON discipline defined for profiles. Historical schema v0, including the
four-member public vector, yields RELEASE_CANDIDATE_VERSION_UNSUPPORTED.
A recognized, self-consistent descriptor that declares unsupported state,
connections, side effects or executable/interaction contract versions yields
APPLICATION_UNSUPPORTED before any semantic trial, including when discovered
during read_candidate. Corruption or cross-member contradictions still yield
integrity errors. Every other malformed candidate yields RELEASE_CANDIDATE_INTEGRITY_FAILED
except explicit trusted-toolchain errors. Never extract unvalidated paths.

Bounds: outer 64 MiB; manifest/receipt/interaction each 1 MiB; application ZIP
32 MiB, expanded total 64 MiB, at most 2048 members; trusted authoring bundle
16 MiB. Reject oversized declarations before decompression/allocation. Inner
ZIPs need safe unique regular files, no encryption/directories/symlinks,
absolute/parent/backslash/Windows aliases or case-fold collisions. Application
archive need not use the outer canonical metadata because its exact bytes are
already bound. Require root capability.toml and interaction.json and a safe
existing regular Python entrypoint. Descriptor raw SHA-256 is authoritative.

Syntax: SHA-256 lower-case 64 hex, Git commit/tree/base lower-case 40 hex,
prj_/ver_/ses_ followed by 32 lower-case hex, rc_ followed by 32 lower-case hex.
Application ID follows the profile grammar. Source repository is exactly
{kind, public_identity, identity_sha256}; local means public_identity=null;
remote means a credential-free git:// public identity whose SHA-256 matches.
verified_at is the same valid UTC ISO8601 value in manifest and receipt.

Manifest schema is capy.application-release-candidate/v1, executable contract
capy.script/dev-v0, interaction capy.application-interaction/dev-v0. Handoff
must equal the example exactly, including all required unaccepted/nonperformed
claims. Every bound member name, size and hash matches actual bytes. Receipt
schema/pipeline end in /v1, status PASSED, classification VERIFIED, and
application/project/verification/source/toolchain/time identities match manifest.

Receipt stages are exactly the ordered example stages. All statuses PASSED.
Process stages have integer exit_code=0; source_mutation_check,
package_compare and archive_preserve have null exit. Facts objects have the
exact example keys/types: timed_out false, candidate_unchanged true; package
hashes/sizes agree with application archive; archive preserve matches; interaction
preserve matches canonical size/hash and raw source hash. Counters are
nonnegative integers and stream hashes have SHA-256 syntax. Verification does
not establish semantic acceptance or provenance/signature trust.

Canonical application/interaction.json must equal canonical JSON parsed from
the application's raw interaction.json, whose raw source hash is also bound.
Descriptor ID and contracts, operation ID, all scalar input/result paths,
requiredness, resource slots/counts and artifacts must satisfy the full bundled
DEVKIT-INTERACTION-CONTRACT.md independently. Unknown interaction fields,
invalid paths/types and descriptor/interaction disagreements fail integrity.
The exact accepted wheel may be read as an API specification but no product
validator may import it to outsource candidate integrity validation.

Trusted bundle/wheel/release/implementation identities are exactly those in
the example and profile requirements. Validate actual bundle hash before
inspecting/using it; validate included RELEASE-MANIFEST.json and wheel hash,
filename, source_commit and contracts. Return TOOLCHAIN_UNTRUSTED for a
self-consistent but unapproved identity and TOOLCHAIN_INTEGRITY_FAILED for
corrupt toolchain bytes. Never download a missing toolchain.

Candidate identity is SHA-256 of the canonical JSON of this exact projection:

```
{
  schema: manifest.schema,
  project_id: manifest.project.project_id,
  application_id: manifest.application.id,
  source: manifest.source,
  application_archive_sha256: manifest.application.archive.sha256,
  application_descriptor_sha256: manifest.application.descriptor_sha256,
  interaction: {
    schema: manifest.application.interaction.schema,
    source_sha256: manifest.application.interaction.source_sha256,
    canonical_sha256: manifest.application.interaction.sha256,
    operation_id: manifest.application.interaction.operation_id
  },
  verification_receipt_sha256: manifest.verification.receipt.sha256,
  toolchain: {
    release_binding_commit: manifest.toolchain.release_binding_commit,
    authoring_bundle_sha256: manifest.toolchain.authoring_bundle.sha256,
    wheel_sha256: manifest.toolchain.wheel_sha256,
    interaction_contract: manifest.toolchain.interaction_contract
  }
}
```

manifest.identity_sha256 must equal this hash; release_candidate_id is rc_ plus
its first 32 hex characters. Candidate.bundle_sha256 binds the complete outer
bytes, not only this projection. All returned model fields must derive from
validated bytes. Pure read_candidate/read_profile functions execute no code,
create no filesystem state, and use no external service.
