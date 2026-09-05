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

POSIX execution uses a launch gate and separate guardian. The guardian observes
PID/parent/group/birth metadata, retains the identity lock descriptor, and kills
the owned tree when the owner closes its control pipe or exits. Applications
never inherit that lock descriptor. Windows uses suspended process creation,
assignment to a non-breakaway Job, and documented thread resume APIs. The Job
has KILL_ON_JOB_CLOSE. Every normal or exceptional return terminates residual
descendants and drains bounded unbuffered streams before accepting cleanup.

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
