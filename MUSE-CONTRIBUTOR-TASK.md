If this task encounters a small implementation or environment blocker,
repair it within this task and continue; do not create a new gate or request
owner authorization unless the blocker changes the authorized product/safety
boundary.

# Frozen Muse Contributor task — acceptance core V0

You are the bounded implementation contributor. Your exact model is selected
externally as muse-spark-1.3-contributor through official Muse Code. Do not
self-certify model identity, product acceptance, or contributor quality.

Work only in this public synthetic repository at /workspace. Read AGENTS.md,
all spec/ contracts, frozen interface modules, and visible tests. Implement the
assigned core completely using Python 3.11+ standard library only. The product
uses zero model, provider, Developer, or runtime dependencies/calls.

You own independent V1 candidate validation, acceptance-profile validation,
cross-binding and interaction expectations, bounded offline case execution,
exact semantic/artifact comparison, secret checks, cleanup, and deterministic
portable receipt/rejection projection. Preserve these public entrypoints:

- candidate.read_candidate(payload: bytes) -> models.Candidate
- profile.read_profile(payload: bytes) -> models.Profile
- acceptance.evaluate(candidate, profile, release: dict, work_root: Path)
  -> models.Evaluation

Read the exact installed DevKit from the already-public fixture wheel when
needed for its mechanical invocation format. Treat it as the application API,
not as a candidate or profile integrity validator. Do not import any Developer
module or copy a Developer validator. Synthetic application source, tests,
conformance or interaction prose cannot override the independently supplied
acceptance profile. An intact, VERIFIED bundle can still be semantically wrong.

Writable source paths are exactly:

```
src/capy_application_acceptor/candidate.py
src/capy_application_acceptor/profile.py
src/capy_application_acceptor/acceptance.py
src/capy_application_acceptor/execution.py
src/capy_application_acceptor/comparison.py
src/capy_application_acceptor/projection.py
src/capy_application_acceptor/process.py
src/capy_application_acceptor/codec.py
src/capy_application_acceptor/interaction.py
src/capy_application_acceptor/scan.py
src/capy_application_acceptor/constants.py
src/capy_application_acceptor/validation.py
tests/contributor/test_*.py
```

Other existing files are frozen, including models.py, errors.py, CLI stubs,
public tests/helpers/fixtures, specifications, this packet, tools, Git metadata,
README, release metadata and workflows. You may add your own meaningful tests
only under tests/contributor. You may create scratch under /tmp and normal
Python bytecode ignored by Git. Do not alter frozen tests to make them pass.

Astra owns database durability, locking/recovery/replay, CLI integration, release
packaging, CI, hidden evaluation, source review, Git commits, and final outcomes.
Those integrations deliberately remain stubs at this stage. Your core should
return complete validated models and Evaluation objects for those integrations.
Do not implement or modify Astra-owned surfaces.

Required visible qualification commands from /workspace:

```
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```

You may also use tools/core_driver.py with copied fixtures and a temporary
release JSON matching the documented release interface. No extra dependencies
or network installation is needed: venv/ensurepip and the included exact wheel
are available. The starting visible suite has 12 tests and fails only because
core interfaces deliberately raise NotImplementedError. Known valid greeting
and artifact fixtures have been independently executed with the exact public
wheel; the artifact expected byte count is 19.

Do not inspect paths outside /workspace except ordinary Python/runtime files
needed by commands and task-owned /tmp. Never inspect credentials, process
secret state, personal context, other repositories, or host paths. Do not use
network research or shell network. Do not disable or bypass the sandbox. Do
not spawn agents or nested sessions. Do not commit, push, publish, merge,
release, install an application, bind a workspace, or deploy anything.

Run 1 is passively observed. No hidden tests or hidden expected patches will
be supplied. After implementation and visible checks, stop and report changed
files, exact tests/results, remaining uncertainty, and any actual blocker.
The outer process will preserve your untouched output before scoring it.
