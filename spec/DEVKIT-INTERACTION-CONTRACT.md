# Portable interaction authoring contract — provisional dev-v0

`capy.application-interaction/dev-v0` lets one portable, one-shot application
carry developer-authored human meaning beside its executable
`capability.toml`. It is a provisional authoring schema, not a runtime contract
or independent acceptance decision.

The root `interaction.json` object has exactly:

```text
schema, application_id, title, purpose, not_for, operation, boundaries
```

There is exactly one operation. Its request fields must cover every closed
scalar input-schema leaf exactly once, including effective requiredness through
nested optional objects and any schema-valid safe default. Its resource fields
must exactly match descriptor slots and counts. Result facts identify scalar
result-schema leaves. Artifact-generation applications must declare exactly the
fixed filenames in `result_schema.properties.artifact_filenames.items.enum`;
read-only applications declare none.

The operation object has exactly:

```text
operation_id, title, user_outcome, description,
request_fields, resource_fields, examples, common_misunderstandings, result
```

Each request field has exactly:

```text
field_id, label, description, required, input_kind, safe_default,
examples, clarification_question
```

`field_id` is a dotted path into the input schema. Allowed input kinds are
`text`, `long_text`, `number`, `boolean`, and `choice`; `choice` is required for
a string enum. A required field has a null safe default. An optional field may
have null or one scalar value accepted by its exact executable schema.

Each resource field has exactly:

```text
slot, label, description, required, minimum_count, maximum_count,
input_kind, examples, clarification_question
```

`input_kind` is `file`; slot identity, requiredness, and counts equal the
descriptor declaration. The result object has exactly `presentation`, `facts`,
and `artifacts`. A fact has exactly `path` and `label`; an artifact has exactly
`filename` and `label`. Presentation is `facts` without artifacts and
`artifact_result` with artifacts.

Each boundary has exactly:

```text
boundary_id, request_class, explanation, nearest_operation_ids
```

At least one boundary and one `not_for` statement are required. Every nearest
operation ID equals the contract's single operation ID. Unknown keys fail
closed. Source is at most 64 KiB; lists and text are bounded; empty, untrimmed,
NUL-containing, non-finite, malformed, excessively nested, or invalid UTF-8
content is rejected.

The profile supports stateless, connection-free `read_only` and
`artifact_generation` capabilities only. It rejects open input objects, arrays,
state, connections, scope mutation, and external effects without reducing what
the underlying execution contract supports.

Validate and optionally project canonical UTF-8 JSON with:

```bash
python -m capy_script interaction-check ./application
python -m capy_script interaction-check ./application --output ../interaction.canonical.json
```

Canonical bytes use sorted object keys, compact separators, finite JSON values,
and no trailing newline. Validation never rewrites application source. An
output path must remain outside the application directory.

Human text is plain text. The validator proves structural consistency only; it
does not establish factual completeness, domain correctness, authority,
workspace or team policy, installation, acceptance, publication, binding, or
deployment.
