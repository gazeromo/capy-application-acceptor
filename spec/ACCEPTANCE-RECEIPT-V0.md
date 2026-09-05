# Independent acceptance V0 — frozen execution and evidence contract

`read_candidate(bytes)` and `read_profile(bytes)` return the frozen models or
raise AcceptorError with a stable code and public-safe constant detail.
`evaluate(candidate, profile, release, work_root)` returns Evaluation for a
valid semantic trial, or raises AcceptorError for unsupported/input/environment
failure. It may create only children of the supplied empty owned root and must
leave the root empty on every return. Cleanup failure raises
`CLEANUP_FAILED` and must never return ACCEPTED. The caller owns SQLite/locks
and the work_root itself. Do not expose databases to application subprocesses.

Release is exactly `{contract, version, implementation_commit,
implementation_tree}`. Contract is `capy.independent-application-acceptance/v0`,
version is `0.1.0`, and identities are lower-case 40-hex. Tests pass a fixed
synthetic identity; packaged identities will be installed by Astra's release
builder. Reject unknown/malformed release objects. Do not infer Git identity.

Identity is exactly `{candidate_bundle_sha256, candidate_release_candidate_id,
profile_bundle_sha256, profile_id, application_id, acceptor}` where acceptor is
release. identity_sha256 is SHA-256 of canonical JSON (same no-trailing-newline discipline as
profiles), and acceptance_id is `acc_` plus its first 32 hex characters.

Candidate/profile application mismatch is `APPLICATION_PROFILE_MISMATCH`;
unsupported descriptor state/connections/side-effect or contracts raise
`APPLICATION_UNSUPPORTED`. Profile/toolchain trust mismatch raises
`TOOLCHAIN_UNTRUSTED`. Interaction mismatch is a semantic
`REJECTED_INTERACTION_MISMATCH`. Candidate integrity is checked before execution.

For each case use a fresh disposable application copy and offline virtualenv.
Install only the validated included wheel using `--no-index --no-deps`. The
application executes its declared Python entrypoint, not its own tests or
conformance fixtures, receives canonical request JSON on stdin, and uses the
accepted DevKit API. Read `DEVKIT-CONTRACT.md`, `DEVKIT-INTERACTION-CONTRACT.md`,
and the fixed wheel within the public fixture for exact mechanical resource,
connection, and result formats. Do not import Developer or runtime code.

All application resources come from the profile, with verified hashes and
safe copied files. Supply resource manifests and slot declarations from the
validated descriptor, an exact empty connection manifest, and a dedicated
output directory. The empty connection manifest is exactly
`{"schema":"capy.connection-manifest/v0","invocation_id":"acceptance-case","connections":[]}`. Fresh child HOME/USERPROFILE and TMP/TEMP/TMPDIR are owned
empty directories. Only minimal platform PATH/SystemRoot/Windows bootstrap
facts may be inherited. Set PYTHONNOUSERSITE=1, PYTHONDONTWRITEBYTECODE=1,
PIP_NO_INDEX=1, PIP_DISABLE_PIP_VERSION_CHECK=1, GIT_CONFIG_NOSYSTEM=1,
GIT_CONFIG_GLOBAL to the platform null device, and GIT_TERMINAL_PROMPT=0.
Do not inherit provider/GitHub/cloud credentials or Capy/Developer/runtime roots.

Bound wall time, stdout and stderr while reading, not after unbounded capture.
Terminate and reap the child process tree on timeout or exceeded output limits
on all target platforms. Per-case timeout is the minimum of profile and
descriptor limits. Environment setup has a separate hard 60-second timeout and
bounded output. Environment unavailability is `EXECUTION_ENVIRONMENT_UNAVAILABLE`.
Do not run candidate code before input/toolchain/secret checks pass.

The DevKit success envelope is the result object plus a mechanical artifacts
list of filenames; remove only that mechanical field before comparing result.
Success requires exit 0, exactly one JSON result envelope, matching result,
and every declared artifact collected before cleanup. Stable expected failures
require exit 2, empty stdout, and exactly one stderr line containing the
DevKit stable code, optionally followed by colon-space and bounded safe detail; unhandled exceptions,
non-JSON or multiple outputs, inconsistent status/exit, and other exit codes
are rejected. Reject missing/extra/duplicate/undeclared files, symlink artifacts,
wrong sizes/digests, wrong bytes, and artifact paths escaping the output root.
Compare exact JSON values/types, exact failure codes, and exact artifact sets
and bytes. Never accept solely because candidate tests passed.

Scan all candidate application members before execution and bounded child
outputs/artifacts afterward for API/provider keys, GitHub tokens, PEM/OpenSSH
private keys, bearer-token and obvious credential assignments, and the exact
public campaign canary `CAPY_ACCEPTOR_SECRET_CANARY_V0`. A match yields
`REJECTED_SECRET_BOUNDARY`, with no matched value or raw data in diagnostics.
The scan is defense in depth, not a proof that no secret exists.

Canonical portable documents have exactly these top-level fields:

- schema: accepted `capy.independent-application-acceptance/v0` or rejected
  `capy.independent-application-rejection/v0`;
- acceptance_id, identity_sha256, identity as defined above;
- status: ACCEPTED or REJECTED;
- classification: ACCEPTED or the first rejection in case order;
- source: exact manifest.source;
- application: `{archive_sha256, descriptor_sha256, interaction_sha256,
  execution_contract, interaction_contract}`;
- toolchain: exact manifest.toolchain;
- cases: ordered case projections below;
- secret_scan: `{status: "PASSED" | "REJECTED", findings: [] | ["SECRET_PATTERN"]}`;
- cleanup: `{status: "CONFIRMED"}`;
- non_claims: exact ordered list in V0-NON-CLAIMS.json.

Early secret/interaction rejection has cases=[] and its causal classification.
Otherwise run all bounded cases in profile order. Case projection is exactly
`{case_id, matched, classification, expected, observed}`. Each expected/observed
is exactly `{status, result_sha256, artifacts, failure_code}`. Result SHA-256
binds canonical result JSON for ok; it is null otherwise. Artifacts are sorted
by filename and exactly `{filename, sha256, size_bytes}`. Observed status is
ok, failed or error; failed has stable failure_code, error has null result and
failure_code. Invalid/unsafe artifact names are not projected into the report.

Matched cases use `CASE_MATCHED`. Mismatches use, in causal precedence:
`REJECTED_SECRET_BOUNDARY`, `REJECTED_CASE_TIMEOUT`,
`REJECTED_OUTPUT_LIMIT`, `REJECTED_APPLICATION_EXIT`,
`REJECTED_FAILURE_CODE_MISMATCH`, `REJECTED_RESULT_MISMATCH`,
`REJECTED_ARTIFACT_SET_MISMATCH`, `REJECTED_ARTIFACT_BYTES_MISMATCH`.
Unexpected success/failure uses RESULT_MISMATCH; expected failed with different
code uses FAILURE_CODE_MISMATCH. Every accepted projection must have all cases
matched, all secret checks PASSED, and cleanup CONFIRMED.

Evaluation.case_records are local-only diagnostics with case_id/order,
classification, exit_code, bounded stdout/stderr SHA-256/byte/truncation counts,
duration, and tool-free facts. Native-path-containing raw stream digests and
durations must not enter the portable document: artifacts may cause paths in
the DevKit's mechanical envelope. Portable bytes must be identical across
machines for the same inputs and release. No raw output, wall-clock timestamp,
username, hostname, native path, credential, or operational duration is portable.

V0 is qualified only for synthetic test-owned applications. Disposable roots
and scrubbed subprocesses do not sandbox malicious arbitrary Python. No
publication, installation, workspace binding, runtime import, or deployment is
performed. The final package has zero model/provider dependencies or calls.
