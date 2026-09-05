# Capy Application Acceptor

Independent, model-free acceptance of copied Capy V1 release candidates against separately frozen synthetic acceptance profiles.

Status: V0 implementation and package qualified under the owner platform amendment. Exact evidence-head CI, closure review and merge status are recorded in the campaign.

The `capy-acceptor` CLI validates a copied interaction-aware `.capyrc` candidate
and an independently frozen `.capya` profile, executes bounded test cases, and
stores an exact portable acceptance receipt or causal rejection report. It has
no runtime dependencies beyond Python 3.11+ and no model calls. SQLite records
local attempts and events; copied inputs and documents are content-addressed.

Ubuntu/Linux and Windows provide candidate execution backends. **Native
candidate execution on unprivileged macOS is unsupported** and fails closed
with `EXECUTION_CONTAINMENT_UNAVAILABLE`. macOS supports parsing, validation,
identity, durable inspection/replay and packaging. The owner-authorized
[platform amendment](spec/PLATFORMS.md) preserves whole-tree cleanup as a
requirement for every acceptance.

Build the exact clean source twice with `python tools/build_release.py`, then
install the resulting wheel offline with `python -m pip install --no-index
--no-deps dist/capy_application_acceptor-0.1.0-py3-none-any.whl`.

```sh
capy-acceptor doctor --json
capy-acceptor profile inspect --profile example.capya --json
capy-acceptor accept --candidate example.capyrc --profile example.capya --json
capy-acceptor acceptance inspect --acceptance-id acc_… --json
```

Set `CAPY_ACCEPTOR_DATA_ROOT` to use an explicit test-owned local data directory.
Accepted/rejected replay returns the same stored portable bytes without
executing the candidate. Read commands exit 0, semantic rejection exits 1, and
input/tool errors exit 2. Local inspection includes operational times and
stream hashes; portable documents contain neither native paths nor raw output.

Run `PYTHONPATH=src python -m unittest discover -s tests -v`,
`python -m compileall -q src tests oracle`, `python tools/secret_scan.py .`, and
`python tools/qualify.py` for source, format, scan, reproducible-build and
installed-wheel qualification. CI compares exact Linux/Windows portable
documents and all three platforms' wheel/release bytes. The macOS suite proves
execution refusal and non-execution portability. The original Muse oracle and
scores remain immutable campaign evidence, separate from the corrected product
oracle and final platform qualification.

This public repository contains only synthetic, test-owned material. It grants no software license: copyright 2026, all rights reserved. Public visibility permits review and the explicitly authorized contributor experiment; it does not change licensing.

V0 does not claim safe execution of arbitrary malicious code, stateful or connection-bearing application acceptance, runtime installation, binding, publication, or deployment.
