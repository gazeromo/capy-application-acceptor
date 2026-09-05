# O1 — Distinct source-file and artifact-name grammars

Independent read-only adjudication by /root/scaffold_contract_review, after
Run 1 scoring and while the already frozen Run 2 packet executes. This finding
has not been disclosed to Muse. It does not change the original first-pass score.

The actual Developer0.4.0 VERIFIED candidate total.capyrc, SHA-256
21923a5752a314ca502a141861e614829b3d8b2d006c54622d83d9ca8503aec6,
contains a regular .gitignore with only bytecode ignore patterns. The frozen
oracle wrongly rejects this, _helpers.py and pkg/__init__.py as unsafe_segment.
The candidate specification permits safe regular source paths and does not
apply the profile resource/artifact basename grammar to them.

Reviewer verdict: genuine oracle defect; correction scope approved:

- Separate source-path validation, including entrypoint checks, from strict
  profile resource/artifact names.
- Permit safe dotfiles and leading underscores; retain traversal, absolute,
  separator, control-path, Windows alias, collision and symlink protections.
- Add positive dotfile/module regressions and unsafe-path negatives.
- Preserve the original oracle and original 65-vector scores unchanged.
- Publish a separately attributed correction commit, version/digest and tests
  after Contributor scoring. Do not feed hidden content to active Muse Run 2.

Original oracle.py SHA-256 remains
b3d00445cc6da570c7bd55173bcc3ff3a96a447ae1f4050ca8ca24ae95a9fba7.
Original hidden aggregate remains
34f094d974ff4f377f6b60333aa4697420ebde8a66f0a27062f5dd6797888b58.
No oracle bytes were changed during adjudication. Product source repair I1
was independently confirmed by /root/muse_run1_source_review and will likewise
be attributed to Astra after the Muse experiment terminalizes.


## O2 — Strict numeric representation in portable bindings

The same independent reviewer confirmed that the frozen oracle accepts an
expected artifact size of19.0 instead of19 and a toolchain bundle size of31836.0
instead of31836. Observed artifact sizes already reject this alias. Approval:
use strict JSON-type/canonical-byte equality for expected projections, portable
receipt bindings (including toolchain), and matched-case comparisons. Preserve
semantic rules; add valid-document and numeric-alias regressions. Publish after
Muse scoring in a separately attributed product-oracle correction. Original
oracle and both original65-vector scores remain unchanged. No feedback to Muse.
