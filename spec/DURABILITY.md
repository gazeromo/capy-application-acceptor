# Local durable execution

`CAPY_ACCEPTOR_DATA_ROOT` selects an explicit local root. Without it the CLI uses
the operating system's application data directory. SQLite schema 1 holds an
index and append-only operational events; copied candidates, profiles and
portable terminal documents are independently addressed by SHA-256.

Each acceptance identity owns a nonblocking OS lock. Exact terminal replay
revalidates copied bytes and returns the stored canonical document without
application execution. A changed candidate, profile or implementation yields
a different identity. Different identities may execute concurrently.

An abandoned PREPARING or RUNNING attempt becomes INTERRUPTED after acquiring
its lock and cleaning its marked work directory. Retries retain prior case and
event generations. An uncertain marker or cleanup failure fails closed and
withholds a portable acceptance receipt. Only matching attempt ID, nonce, root
and ownership marker authorize recursive cleanup. Lock files remain in place.

Linux execution uses a separate PR_SET_CHILD_SUBREAPER supervisor which adopts
orphaned descendants even when they detach. It retains the identity lock and
kills and reaps every child before releasing ownership. Applications inherit
only standard streams. Windows assigns the process atomically to a
non-breakaway KILL_ON_JOB_CLOSE Job through PROC_THREAD_ATTRIBUTE_JOB_LIST
during CreateProcessW; there is no create-before-assignment window. Normal
cleanup confirms zero active Job processes. Every return drains bounded
unbuffered streams before accepting cleanup.

Native unprivileged macOS is not an accepted V0 execution backend. Fresh
candidate execution fails closed with EXECUTION_CONTAINMENT_UNAVAILABLE,
before wheel setup or any candidate process. Parsing, validation, durable
state, inspection and exact replay remain available. See PLATFORMS.md for the
explicit owner-authorized amendment to original plan section 23.

This supports bounded public synthetic applications, not arbitrary malicious
Python. It is not filesystem or network isolation and provides no hostile-code
sandbox claim. In particular, V0 must not be used for untrusted code on a host
holding valuable state. Production, providers, runtime authority and external
effects remain outside this contract.

Portable bytes exclude times, native paths, executable locations, PIDs and raw
streams. Local inspection contains timing and bounded stream hashes outside
the portable document. JSON CLI adds one newline as output framing; the stored
canonical receipt/report has no newline. Exit codes: accepted/read commands 0,
semantic rejection 1, malformed input or tool failure 2.

Implementation identity is embedded in the wheel. Source use requires clean
runtime/build files at the recorded implementation commit and exact tree.
Evidence-only later commits retain that identity through release/IMPLEMENTATION.json.
