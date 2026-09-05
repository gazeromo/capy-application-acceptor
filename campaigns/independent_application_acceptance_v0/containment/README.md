# Layered containment continuation

This continues the same campaign from `f6d3e8ac3b31cfef8bc3ecec19bc72f1651f2c97`
under owner direction D-204. The earlier macOS failures remain preserved.

The official Linux Muse Code 1.0.3-R2198.1 binary runs in a disposable Docker
container with no host bind mounts, real home, sibling repositories, credentials,
SSH agent, Docker socket, or host namespaces. The worker has only a public
task-owned source volume, separately read-only Git metadata, and temporary
state. Its native Muse sandbox remains enabled with shell network restricted.
The reviewed seccomp profile retains deny-by-default behavior while allowing
the user-namespace operations required for the nested native sandbox. The
worker is not privileged and has no Linux capabilities.

A separate gateway owns model transport. It accepts only the exact Contributor
model route, requires a separate random worker capability, and consumes a
one-use authenticated bootstrap from official host Muse. Provider authentication
stays only in gateway memory. Neither capability values nor provider credentials
are included in this evidence. Gateway catalog/config startup data is frozen
public metadata; provider response events, not that catalog, prove live identity.

Synthetic transport attempts 1–7 exposed startup/routing, fixture protocol,
nested-sandbox, probe, reminder, and Git-protection issues. These were local
fixture tests with zero real provider requests. Attempt 8 passed every required
matrix item and the focused gateway boundary regression. An independent
read-only reviewer accepted the configuration before real credential bootstrap.

One live host identity request established the gateway connection. A subsequent
live worker session made two model requests and one bash call. All three provider
requests succeeded and every provider response identified
`muse-spark-1.3-contributor`. The unchanged probe again passed workspace writes,
Git protection, host privacy, arbitrary and numeric proxy-network denial, and
credential non-projection. The official executable digest remained unchanged.

Full redacted exports remain local because they preserve encrypted reasoning.
These receipts bind their hashes and project the model, permission, tool, and
terminal facts. Visible JSONL is a labeled subset, not a claim to be the full
trajectory. Synthetic-provider outputs are explicitly not live-model evidence.

**Qualification: containment passed. Muse implementation runs: zero. Coding
ability and product acceptance: unevaluated.** Next is the frozen public
scaffold, separate hidden oracle, and passive first implementation run.

Muse's documented normal sandbox keeps the rest of the filesystem read-only;
the outer container supplies the privacy boundary. See the official
[contained execution contract](https://github.com/meta-models/meta-model-cookbook/blob/main/04_muse_code/04_contained_execution/README.md).
