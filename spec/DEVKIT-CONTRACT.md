# Capy Script Contract — provisional dev-v0

`capy.script/dev-v0` is an external developer contract. It is provisional and
must not be treated as a stable production ABI.

## Descriptor

Every script is a directory containing `capability.toml` and a Python
entrypoint. The descriptor declares:

```text
schema, id, name, description, entrypoint, side_effect,
timeout_seconds, memory_mb, state_required,
input_schema, result_schema, resources, connections
```

Allowed side-effect classes are `read_only`, `artifact_generation`,
`scope_state_mutation`, and `external_effect`.

Resource entries declare a semantic `name`, `required`, `min_items`, and
`max_items`. Connection entries declare a semantic `name`, `contract`, allowed
`operations`, and `required`. Provider credentials are never part of either
declaration.

An interaction-aware portable application also carries root `interaction.json`
with schema `capy.application-interaction/dev-v0`. The executable descriptor
remains authoritative. The interaction file supplies provisional human meaning
for one operation and must cross-check exactly against executable scalar input
leaves, resource slots/counts, scalar result facts, fixed artifacts, and the
side-effect class. See `INTERACTION-CONTRACT.md`. This authoring profile does
not change `capy.script/dev-v0` or add a runtime helper.

## Entrypoint

The entrypoint constructs one context:

```python
from capy_script import Context

ctx = Context()
request = ctx.request
packages = ctx.resource("packages")
quote = ctx.connection("fedex_rates").call("quote", request)
ctx.artifact("quote.json", b"{}\n")
ctx.complete(quote)
```

- `ctx.request` is exactly one JSON object from standard input.
- `ctx.resource(name)` returns the resources projected into that declared
  semantic slot. Resources expose `filename`, `digest`, `path`, `read_bytes()`,
  and `read_text()`; `collection.one()` requires exactly one.
  A declared optional slot with no projected resources returns an empty
  collection; an undeclared slot fails causally.
- `ctx.connection(name).call(operation, payload)` calls one declared semantic
  operation through an invocation-scoped local handle. It never exposes a
  secret.
- `ctx.artifact(name, bytes)` creates one bounded output file and declares it in
  the mechanical result envelope.
- `ctx.complete(result)` validates and writes one JSON-compatible result, then
  exits successfully. Application result schemas do not include the mechanical
  `artifacts` field.
- `ctx.fail(code, safe_detail=None)` emits a stable causal code and exits 2.
- `ctx.state_dir` is available only when state was declared and projected. The
  DevKit supplies no database abstraction.

Uncaught stack traces are developer diagnostics, not product failures.

## Local fixture

A `capy.script-fixture/dev-v0` JSON object supplies `request`, resource source
files, and deterministic connection responses. It contains no real secret.
Conformance expectations use `ok` for successful application results, `failed`
for application causal failures, and `rejected` for bounded local-harness
diagnostics from request validation, resource projection, or required connection
setup before execution. A resource fixture may supply a test-only SHA-256 digest
override to exercise integrity failures.
See `docs/TESTING.md`.

## Boundary

This contract does not provide workflows, scheduling, model access, databases,
HTTP frameworks, authentication, chat, publication, sharing, or deployment.
