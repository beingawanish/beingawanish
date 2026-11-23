-- Canonical DDL for the tables every service shares by convention.
--
-- This is a contract, not a migration. Each implementation reproduces it in its own migration tool
-- (Alembic for Python, Flyway for Java) as the first migration of every service. Column names and
-- types matter: the Debezium outbox connector (infra/connect/connectors/*.json) reads them by name,
-- and a Python and a Java build of the same service must be able to run against the same database.
--
-- PostgreSQL 16. Every service has its own database (ADR-003); these tables live in its public schema.

-- ---------------------------------------------------------------------------------------------
-- Transactional outbox (ADR-003). Written in the same transaction as the business change.
-- Debezium reads INSERTs from the WAL and routes each row to the topic in column "topic".
-- ---------------------------------------------------------------------------------------------
CREATE TABLE outbox (
    id              uuid        PRIMARY KEY,            -- = envelope.eventId (UUIDv7)
    aggregate_type  text        NOT NULL,               -- = envelope.aggregateType
    aggregate_id    text        NOT NULL,               -- = envelope.partitionKey; becomes the Kafka record key
    event_type      text        NOT NULL,               -- = envelope.type (Avro full name); header ce_type
    topic           text        NOT NULL,               -- destination topic, e.g. order.events.v1
    payload         bytea       NOT NULL,               -- Confluent wire format: 0x00, 4-byte schema id, Avro binary
    occurred_at     timestamptz NOT NULL,               -- header ce_time
    producer        text        NOT NULL,               -- header ce_source
    correlation_id  text        NOT NULL,               -- header correlation_id
    causation_id    text,                               -- header causation_id
    traceparent     text,                               -- header traceparent
    tracestate      text,                               -- header tracestate
    created_at      timestamptz NOT NULL DEFAULT now(),
    published_at    timestamptz                         -- set only by the polling relay fallback
);
-- The polling relay (fallback mode) scans unpublished rows in insertion order.
CREATE INDEX outbox_unpublished_idx ON outbox (created_at) WHERE published_at IS NULL;
-- Housekeeping deletes rows older than 7 days (Debezium has long since read them from the WAL).
CREATE INDEX outbox_created_at_idx ON outbox (created_at);

-- Debezium connects as role "debezium" (created by infra/postgres/init). It needs to read this table
-- and only this table. The publication is created here, by the service, so the connector can run
-- with publication.autocreate.mode=disabled and no CREATE privilege.
-- The guard keeps the migration runnable in Testcontainers databases where the role does not exist.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'debezium') THEN
        GRANT SELECT ON outbox TO debezium;
    END IF;
END
$$;
CREATE PUBLICATION outbox_pub FOR TABLE outbox;

-- ---------------------------------------------------------------------------------------------
-- Inbox for idempotent consumers (ADR-006). The insert happens in the same transaction as the
-- handler's business change. A unique violation means "already processed": skip and commit offset.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE inbox (
    message_id      text        NOT NULL,               -- envelope.eventId, or provider event id for webhooks
    consumer        text        NOT NULL,               -- consumer group or webhook name, e.g. order-svc, psp-webhook
    message_type    text        NOT NULL,
    source_topic    text,                               -- null for webhooks
    source_partition int,
    source_offset   bigint,
    received_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, consumer)
);
-- Housekeeping deletes rows older than the longest topic retention plus margin (100 days).
CREATE INDEX inbox_received_at_idx ON inbox (received_at);

-- ---------------------------------------------------------------------------------------------
-- HTTP idempotency keys (ADR-012). Only for services with an unsafe public POST.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE idempotency_key (
    caller          text        NOT NULL,               -- JWT subject (or client id for machine callers)
    key             text        NOT NULL,               -- Idempotency-Key header
    request_hash    text        NOT NULL,               -- SHA-256 of method + path + canonical JSON body
    status          text        NOT NULL CHECK (status IN ('IN_PROGRESS', 'COMPLETED')),
    response_status int,
    response_headers jsonb,
    response_body   bytea,
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,               -- created_at + 24h
    PRIMARY KEY (caller, key)
);
CREATE INDEX idempotency_key_expires_idx ON idempotency_key (expires_at);

-- ---------------------------------------------------------------------------------------------
-- Saga state (ADR-008). Only in order-svc and returns-svc.
-- One row per saga instance; optimistic locking on version; one transition row per state change.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE saga_instance (
    saga_id         text        PRIMARY KEY,            -- orderId or returnId
    saga_type       text        NOT NULL,               -- ORDER | RETURN
    state           text        NOT NULL,
    data            jsonb       NOT NULL,               -- saga-local data: ids minted for each step, amounts, attempts
    version         bigint      NOT NULL DEFAULT 0,     -- optimistic lock; also envelope.aggregateVersion of emitted events
    deadline_at     timestamptz,                        -- when the current step times out; null when terminal or idle
    step_attempts   int         NOT NULL DEFAULT 0,     -- resends of the current step's command
    correlation_id  text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    completed_at    timestamptz
);
-- The deadline sweeper: SELECT ... WHERE deadline_at <= now() ORDER BY deadline_at
-- FOR UPDATE SKIP LOCKED LIMIT 100. Several replicas can sweep in parallel without double work.
CREATE INDEX saga_deadline_idx ON saga_instance (deadline_at) WHERE deadline_at IS NOT NULL;

CREATE TABLE saga_transition (
    saga_id         text        NOT NULL REFERENCES saga_instance (saga_id),
    seq             bigint      NOT NULL,               -- = saga_instance.version after the transition
    from_state      text        NOT NULL,
    to_state        text        NOT NULL,
    trigger_type    text        NOT NULL,               -- event type, DEADLINE, or OPERATOR
    trigger_id      text,                               -- eventId of the trigger, if any
    at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (saga_id, seq)
);
