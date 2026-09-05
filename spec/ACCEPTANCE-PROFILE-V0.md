# Acceptance profile V0 — frozen core contract

A complete `.capya` is a deterministic ZIP with `ACCEPTANCE-PROFILE.json`
first, then `fixtures/` members sorted, then `expected/` members sorted. No
unreferenced members. ZIP_STORED, Unix create_system 3, regular mode 0100644,
1980-01-01 00:00:00, no extras/comments/encryption/symlinks/directories. Rebuilding
with these fields must reproduce every byte (including absence of trailing data).
JSON is UTF-8, sorted keys, separators comma/colon, ensure_ascii=False,
allow_nan=False, and no trailing newline. Duplicate JSON keys, nonfinite numbers,
invalid Unicode, depth over 32 and unsafe names are invalid. Booleans are not
integers. Exact result comparison uses canonical JSON bytes: true, 1, and 1.0
are distinct representations. Objects are closed at every schema-owned level;
request/result values are arbitrary finite JSON governed by application schemas.

Top-level exact keys:
`schema, profile_id, application_id, candidate_requirements,
interaction_expectations, cases, limits, non_goals`.

- schema: `capy.application-acceptance-profile/v0`.
- profile_id: ASCII `[a-z][a-z0-9._/-]{0,127}`, no empty/dot/parent segment.
- application_id: `[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+`, max 128.
- non_goals: exactly the ordered values in `V0-NON-CLAIMS.json`.

Candidate requirements have exactly these fields and supported values:

| Key | Value |
| --- | --- |
| release_candidate_schema | capy.application-release-candidate/v1 |
| execution_contract | capy.script/dev-v0 |
| interaction_contract | capy.application-interaction/dev-v0 |
| toolchain_release_binding_commit | 24b6418c0ee2dada5a08f78ff6752bb43f9d8e16 |
| toolchain_wheel_sha256 | 56c9f6c930b21d600a2e8f10da7a3e92f5cfbf1c6d91490d170d1790e5555603 |
| toolchain_authoring_bundle_sha256 | 12e492ec2dce11b4227d10bdf9385705a60bc12a88fec0073ff48a87b2a57a57 |
| side_effect | read_only or artifact_generation |
| state_required | false |
| connections | [] |

Interaction expectations have exactly these keys:

- purpose: null (unspecified) or nonempty string, maximum 4000 characters;
- operation_id: exact nonempty dotted identifier;
- not_for: unique nonempty strings required as a subset;
- request_fields: ordered exact list of `{field_id, required}` objects;
- resource_fields: ordered exact list of `{slot, required, min_items, max_items}`;
- result_fact_paths: unique ordered list of exact scalar dotted paths;
- artifact_filenames: unique ordered list of safe basenames;
- boundaries: unique boundary IDs, each `{boundary_id, nearest_operation_ids}`.

Profile min_items/max_items map to interaction minimum_count/maximum_count.
Requiredness is strictly boolean. Counts are integers 0..16 with min<=max.
Required slots have positive minimum. Compare declared fields and resource
counts exactly, and specified not_for/boundaries as exact subsets. A boundary's
nearest-operation list must match exactly. Do not use language-model judgment.

Every case is exactly `{case_id, request, resources, expect}`. case_id is unique
ASCII `[a-z][a-z0-9_-]{0,63}`. request is an object. Every resource is exactly
`{slot, filename, member, sha256}`; slot is unique within a case and names a
profile resource field. filename is a safe basename, member is exactly
`fixtures/<case_id>/<filename>`, and sha256 binds bytes. Projected counts must
satisfy every profile slot's requiredness/counts, including zero for absent
optional slots. Fixtures may not be shared by two entries.

Expect is exactly `{status, result, artifacts, failure_code}`. For `ok`, result
is an object and failure_code is null. For `failed`, result is null, artifacts
is [], and failure_code matches `[A-Z][A-Z0-9_]{0,95}`. At least one ok and one
failed case are required. Each expected artifact is exactly
`{filename, member, sha256}`, with member `expected/<case_id>/<filename>`.
Filenames are unique and must match the profile artifact declarations for an
ok case; expected bytes and hashes are authoritative. Failed cases have none.

A safe portable basename matches `[A-Za-z0-9][A-Za-z0-9._-]{0,127}` and is not a
Windows reserved device name, dot/parent segment, trailing-dot name, or alias
under case folding. No colon, slash, backslash, absolute or traversal name.
All resource/artifact identifiers and member paths are validated before writing.

Limits is exactly these integer keys, positive and at most the hard ceiling:

| Key | Hard ceiling |
| --- | ---: |
| max_cases | 32 |
| max_resources_per_case | 16 |
| max_fixture_bytes | 8388608 |
| max_expected_artifact_bytes | 8388608 |
| max_request_bytes | 65536 |
| timeout_seconds | 30 |
| max_stdout_bytes | 1048576 |
| max_stderr_bytes | 1048576 |
| max_total_artifact_bytes | 8388608 |

Actual case/resource counts and canonical request bytes must fit limits.
Fixture and expected artifact byte limits apply to each category's aggregate
across the profile. The entire profile is bounded by 32 MiB/1024 ZIP members.
Exceeding a declared/hard bound is invalid before execution. Unsupported
requirements fail `ACCEPTANCE_PROFILE_INVALID`; wrong fixed toolchain identity
fails `TOOLCHAIN_UNTRUSTED`; malformed ZIP/JSON/digest is
`ACCEPTANCE_PROFILE_INTEGRITY_FAILED`. No unknown field is ignored.

Complete bundle SHA-256 is authoritative; profile_id alone never grants trust.
