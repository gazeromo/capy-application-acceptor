# Independent source review — untouched Run2

Reviewer: /root/muse_run1_source_review. Exact commit
15075306a3de409e4e33666680466f3076ced3a6, tree
f52442530be6d17a14b356b280da7b0252a24114. No source edits or hidden-oracle reads.

The specific undeclared-artifact, bounded artifact-byte read, full artifact-tail
scan, duplicate-key, and four receipt integer-size failures are repaired.
The original inherited-pipe deadline now terminated in101ms; overflow in53ms.
Deflated manifest reads and fixed bundle trust ordering are repaired.

Remaining findings: two P1 and three P2:

1. P1 process.py:211: a normal parent with closed/redirected descendant pipes
   returned in77ms while its child remained alive. Windows taskkill/T against
   an already-exited parent PID is not durable tree ownership; buffered
   stream.close can still block. POSIX reproduced; Windows source reviewed.
2. P1 candidate.py:138: a function-local constants import makes the earlier
   MANIFEST_MAX_BYTES use raise UnboundLocalError, swallowed by a broad catch.
   Oversized2MiB interaction and other members were read before rejection.
   The historical peek likewise reads oversized STORED manifests first.
3. P2 profile.py:69: new undocumented1MiB JSON limit rejects a valid profile
   with32cases,40014-byte requests and1206736-byte JSON. Run1 accepts it.
4. P2 comparison.py:146: artifact anomaly precedes failure-code/result
   mismatch, violating the frozen causal ordering.
5. P2 comparison.py/shared parser:1e309 and escaped lone surrogate parse
   successfully then fail canonical projection, producing environment error
   rather than application-output rejection.

Separate integration I1, deliberately not supplied in the repair packet:
codec.py:217 applies artifact basename rules to source paths, rejecting ordinary
.gitignore and Python underscore modules. The actual Developer VERIFIED total
candidate demonstrates this; allowing exactly .gitignore in a process-local
diagnostic lets all other candidate checks pass. No source mutation was made.

All40 visible tests and all65 original hidden vectors pass, but these findings
remain material. No third Muse run. Astra must repair them in distinct commits;
final contributor grade also accounts for the retained-code delta.
