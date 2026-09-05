If this task encounters a small implementation or environment blocker,
repair it within this task and continue; do not create a new gate or request
owner authorization unless the blocker changes the authorized product/safety
boundary.

# Muse Contributor Run 2 — one bounded causal repair

This is the sole allowed repair run for your acceptance-core contribution.
Start from your untouched Run 1 commit fec88e377a12039826a5afa3388b8bb3dd7d4b64.
Read /workspace/MUSE-CONTRIBUTOR-TASK.md and preserve its complete authority,
data, sandbox and writable-path boundaries. The same exact twelve core source
paths and tests/contributor/test_*.py are writable. Everything else remains
frozen. Do not change tests, specifications, task packets, models, errors,
CLI, tools, Git metadata, or other Astra-owned files. Do not spawn agents,
use network, inspect foreign/private state, disable sandbox, commit or push.
Use Python 3.11+ standard library only. Work only inside /workspace and
ordinary runtime/task-owned /tmp. No hidden tests or expected patches are given.

Run 1 completed normally and passed all 25 visible tests. The independent
frozen hidden controller passed 62 of 65 vectors. Three profile error categories
returned ACCEPTANCE_PROFILE_INTEGRITY_FAILED where the required causal code is
ACCEPTANCE_PROFILE_INVALID: unknown profile root field, unknown case field,
and boolean supplied as an integer limit. These are schema-invalid profiles;
malformed ZIP/JSON/digest remains integrity failure. Do not relax validation.

A separate read-only public-contract source review found five P1 and two P2
issues. Repair these within the existing public interfaces:

1. P1, process.run_bounded / _kill_tree: the whole child process tree and its
   pipes do not obey the deadline. A parent spawning a descendant sleeping
   1.3 seconds then exiting returned after 1,385 ms with timeout_seconds=0.1,
   timed_out=false and exit 0. Windows kills only the immediate child. Also,
   a child flushing 20 bytes with stdout limit 8 then sleeping was reported
   as a timeout rather than prompt output overflow. The public contract
   requires incremental bounded reads, bounded wall time, and terminating
   and reaping the child tree on all three target platforms, including
   descendants holding inherited pipes after the immediate parent exits.

2. P1, execution.collect_artifacts / run_one_case / acceptance.evaluate:
   dotfiles are ignored, and unsafe names are filtered but their anomalies
   do not consistently cause rejection. A directory containing .undeclared
   and "bad name.txt" yields an empty artifact list with unsafe-name anomaly;
   expected empty artifacts can consequently match. Every extra/undeclared
   output, unsafe name, directory, or symlink must be rejected, for successful
   and failed cases. Do not expose unsafe names in portable evidence.

3. P1, execution.collect_artifacts: read_bytes allocates and retains whole
   artifact files before checking the aggregate output limit. A huge file
   can exhaust memory before REJECTED_OUTPUT_LIMIT. Enforce the configured
   bounds during collection, including aggregate bounds and causal evidence.

4. P1, execution.run_one_case: only the first 1 MiB + 1 of each artifact is
   scanned for secrets although 8 MiB may be permitted. The public campaign
   canary after that prefix is missed. Scan all permitted artifact bytes.

5. P1, candidate.read_candidate / profile.read_profile / toolchain validation:
   loose manifest reads decompress before metadata/expanded-size validation.
   A roughly 2 KiB DEFLATED ZIP caused a 2 MiB manifest read before rejection.
   Toolchain manifest/wheel reads likewise precede fixed trusted bundle
   validation. Reject unsupported/boundedness violations before unbounded
   decompression/allocation, while retaining the public causal classifications.

6. P2, comparison.parse_success_envelope: duplicate JSON result keys are
   accepted by permissive json.loads. An envelope with message="wrong" then
   message="hello" and artifacts=[] matched expected message="hello".
   Reject duplicate keys, nonfinite values and other malformed JSON before
   semantic comparison or portable projection.

7. P2, candidate verification receipt validation: numerically equivalent
   floating-point values pass equality-only checks for application archive
   size, interaction canonical size and preserve-stage sizes. The V1 contract
   requires precise integer types (booleans are not integers). Preserve the
   strict types and relationships throughout the receipt graph.

Add meaningful regressions only under tests/contributor/test_*.py. Run the
required visible unittest and compileall commands. Report observed results,
changed files and remaining uncertainty. Do not claim final product acceptance
or contributor quality. Stop when finished; there is no third repair run.
