# ADR-0004: Avro with Schema Registry, FULL_TRANSITIVE compatibility, TopicRecordNameStrategy

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** ADR-0005, ADR-0014, contracts/avro/, contracts/tools/contracts.py

## Context

Two teams will build the same services in Python and Java. A Python producer must be readable by a Java consumer and the other way around, byte for byte. Contracts will change over the years. Consumers deploy on their own schedules, so at any moment old and new versions of producers and consumers run side by side, and topics retain old messages for up to 90 days.

We also put several event types on one topic, to keep per-order ordering (ADR-0005).

## Decision

**Format.** Message values are **Avro**, serialised in the **Confluent wire format** (magic byte `0`, 4-byte big-endian schema id, Avro binary). Keys are plain UTF-8 strings.

**Source of truth.** Hand-written `.avsc` files in `contracts/avro/<context>/{events,commands}/`. Shared types (`Envelope`, `Money`, `Address`, `ClaimCheck`, `LineItem`, …) live in `contracts/avro/common/` and are referenced by full name. `contracts/tools/contracts.py bundle` inlines them into self-contained schemas in `contracts/avro-bundled/`. Code generation and registration use only the bundled files, so neither side depends on Schema Registry references.

**Subjects.** `TopicRecordNameStrategy`: subject = `<topic>-<record full name>`, for example `order.events.v1-com.edacommerce.order.OrderPlaced`. This allows many record types per topic, each evolving on its own.

**Compatibility.** `FULL_TRANSITIVE` on every subject. A new version must be readable by every old reader *and* able to read every old message. In practice:

- Add a field only with a default. Remove a field only if it had a default.
- Optional fields are `["null", T]` with `"default": null`, null first.
- Every enum has an `UNKNOWN` symbol and `"default": "UNKNOWN"`, so a new symbol does not break old readers.
- Never rename a field or a record. Never change a type.

**Breaking changes** get a new topic (`order.events.v2`), a period of dual publishing from the outbox (two rows per change), and a migration plan for consumers. The `.vN` suffix and `envelope.version` move together.

**Registration.** Services run with `auto.register.schemas=false` and `normalize.schemas=true`. Only `make schemas` (and the CI job that wraps it) registers, after a compatibility check against the registry. This makes the registry the gate, not a passive store.

**Representation rules for interoperability.**

| Concept | Avro type | Why |
|---|---|---|
| Money | `common.Money{amountMinor: long, currency: string}` | Avro `decimal` maps differently in Python (`Decimal`) and Java (`ByteBuffer` or `BigDecimal` depending on settings); integers do not |
| Identifiers | `string` (UUIDv7 text) | The `uuid` logical type has uneven conversion support; strings are identical everywhere |
| Timestamps | `long` with `timestamp-millis` | Supported natively by fastavro (`datetime`) and Avro Java (`Instant`) |
| Personal data | field property `"pii": true` | Tooling and reviews find it; Avro ignores unknown properties |

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it |
|---|---|---|
| JSON + JSON Schema | Human-readable on the wire; no codegen | Larger messages; JSON Schema compatibility checking is weaker and slower; number handling differs per language |
| Protobuf + registry | Excellent codegen; good evolution story; gRPC friendly | Field-presence rules differ between proto3 languages; less natural with Debezium and Kafka Connect; either is fine, and Avro is the Kafka ecosystem default |
| CloudEvents structured JSON | Standard envelope | Same issues as JSON; we borrow the CloudEvents header names instead (binary mode) |
| `TopicNameStrategy` (one schema per topic) | Simplest; one subject per topic | Forces one record type per topic or a giant union; a union makes every new event type a schema change for all consumers |
| `RecordNameStrategy` | One subject per record type across topics | A record could then evolve differently from what one topic's consumers expect; we want topic-scoped governance |
| `BACKWARD` compatibility (registry default) | Easier to evolve: you may remove fields freely | Only protects new readers; old consumers break on new data; with independent deploys and long retention we need both directions |
| Schema references instead of bundling | No duplication in the registry | Reference support differs between client versions and languages; bundling removes a whole class of interop bugs |

## Consequences

- Every event change is a pull request to `contracts/`, reviewed by the owning team and checked by `make contracts-check` and the registry.
- Generated code: Java uses the Avro Gradle/Maven plugin on `avro-bundled/` (SpecificRecord). Python uses fastavro with dict records validated against the bundled schema, mapped to typed dataclasses at the adapter boundary.
- Consumers must handle `UNKNOWN` enum values (log, treat as "not for me", or route to a safe default) rather than crash.
- The registry is on the write path. Clients cache schema ids, so a registry outage only hurts cold starts and new schemas (`chaos-registry` drill).
- Golden examples in `contracts/examples/` (JSON + raw Avro `.bin`) are the cross-language test fixtures (ADR-0014).

## Trade-offs

We gain compact messages, strict, machine-checked evolution, and byte-level interoperability between languages. We pay with codegen, a registry on the critical path, and the discipline of FULL_TRANSITIVE: some changes that feel small (renaming a field, tightening a type) need a new topic version.

## When to revisit

- The organisation standardises on Protobuf: the envelope, topic layout and compatibility rules carry over.
- Many consumers are browsers or third parties that cannot use a registry: publish a JSON projection on a separate public topic.
- Breaking changes become frequent (more than one new topic version per quarter per context): the domain model is not stable; fix that first.
