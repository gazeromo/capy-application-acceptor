# Independent source review — untouched Run1

Reviewer: /root/muse_run1_source_review. Exact commit
fec88e377a12039826a5afa3388b8bb3dd7d4b64. Public contracts/source and bounded
independent probes only; hidden oracle not opened; no source edits.

Five P1, two P2, no P0:

1. P1 process.py:146: immediate-parent exit bypasses descendant deadline;
   a 1.3-second inherited-pipe child returned after1385ms under a100ms limit.
   Windows killed only direct child. Buffered65536-byte reads delayed overflow.
2. P1 execution.py:113: dotfiles ignored, unsafe entries filtered without
   consistently rejecting them. Empty expected artifacts could match.
3. P1 execution.py:132: whole artifact read_bytes before aggregate bound.
4. P1 execution.py:263: artifact secret scan omitted bytes after1MiB+1,
   despite an8MiB supported ceiling; exact public canary tail was missed.
5. P1 candidate.py:76/profile.py:63: archive manifests decompressed before
   metadata bounds; roughly2KiB compressed input caused2MiB allocation.
   Toolchain reads also preceded fixed trusted hash validation.
6. P2 comparison.py:66: duplicate JSON message keys could produce CASE_MATCHED.
7. P2 candidate.py:511/524/634: equality-only receipt size checks accepted
   numerically equivalent floats in four integer fields.

The original first-pass score remains25/25 visible,62/65 hidden. Review findings
are additional evidence, not hidden-vector count changes.
