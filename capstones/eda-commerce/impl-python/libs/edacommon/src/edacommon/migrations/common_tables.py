"""Migration 1 of every service: the shared tables of contracts/sql/common-tables.sql.

The statements below reproduce the contract DDL statement for statement. Column names and types
matter because Debezium reads the outbox by column name and a Python and a Java build of the same
service must be able to run against the same database (guide §5 rule 15). A test in every service
diffs ``information_schema.columns`` after this migration against the contract file itself.

Usage in ``migrations/versions/0001_common_tables.py``::

    from edacommon.migrations.common_tables import upgrade_common, downgrade_common
    def upgrade() -> None: upgrade_common(op, saga=True)
"""

from __future__ import annotations

from typing import Any

OUTBOX = [
    """CREATE TABLE outbox (
    id              uuid        PRIMARY KEY,
    aggregate_type  text        NOT NULL,
    aggregate_id    text        NOT NULL,
    event_type      text        NOT NULL,
    topic           text        NOT NULL,
    payload         bytea       NOT NULL,
    occurred_at     timestamptz NOT NULL,
    producer        text        NOT NULL,
    correlation_id  text        NOT NULL,
    causation_id    text,
    traceparent     text,
    tracestate      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    published_at    timestamptz
)""",
    "CREATE INDEX outbox_unpublished_idx ON outbox (created_at) WHERE published_at IS NULL",
    "CREATE INDEX outbox_created_at_idx ON outbox (created_at)",
    """DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'debezium') THEN
        GRANT SELECT ON outbox TO debezium;
    END IF;
END
$$""",
    "CREATE PUBLICATION outbox_pub FOR TABLE outbox",
]

INBOX = [
    """CREATE TABLE inbox (
    message_id      text        NOT NULL,
    consumer        text        NOT NULL,
    message_type    text        NOT NULL,
    source_topic    text,
    source_partition int,
    source_offset   bigint,
    received_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, consumer)
)""",
    "CREATE INDEX inbox_received_at_idx ON inbox (received_at)",
]

IDEMPOTENCY = [
    """CREATE TABLE idempotency_key (
    caller          text        NOT NULL,
    key             text        NOT NULL,
    request_hash    text        NOT NULL,
    status          text        NOT NULL CHECK (status IN ('IN_PROGRESS', 'COMPLETED')),
    response_status int,
    response_headers jsonb,
    response_body   bytea,
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    PRIMARY KEY (caller, key)
)""",
    "CREATE INDEX idempotency_key_expires_idx ON idempotency_key (expires_at)",
]

SAGA = [
    """CREATE TABLE saga_instance (
    saga_id         text        PRIMARY KEY,
    saga_type       text        NOT NULL,
    state           text        NOT NULL,
    data            jsonb       NOT NULL,
    version         bigint      NOT NULL DEFAULT 0,
    deadline_at     timestamptz,
    step_attempts   int         NOT NULL DEFAULT 0,
    correlation_id  text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    completed_at    timestamptz
)""",
    "CREATE INDEX saga_deadline_idx ON saga_instance (deadline_at) WHERE deadline_at IS NOT NULL",
    """CREATE TABLE saga_transition (
    saga_id         text        NOT NULL REFERENCES saga_instance (saga_id),
    seq             bigint      NOT NULL,
    from_state      text        NOT NULL,
    to_state        text        NOT NULL,
    trigger_type    text        NOT NULL,
    trigger_id      text,
    at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (saga_id, seq)
)""",
]


def statements(*, saga: bool, idempotency: bool = True) -> list[str]:
    """The DDL for one service. Every service gets outbox + inbox; idempotency_key wherever there is
    an unsafe POST (every service has ``POST /ops/dlq/replay``); saga tables only in orchestrators."""
    out = OUTBOX + INBOX
    if idempotency:
        out += IDEMPOTENCY
    if saga:
        out += SAGA
    return out


def upgrade_common(op: Any, *, saga: bool, idempotency: bool = True) -> None:
    for stmt in statements(saga=saga, idempotency=idempotency):
        op.execute(stmt)


def downgrade_common(op: Any, *, saga: bool, idempotency: bool = True) -> None:
    if saga:
        op.execute("DROP TABLE IF EXISTS saga_transition")
        op.execute("DROP TABLE IF EXISTS saga_instance")
    if idempotency:
        op.execute("DROP TABLE IF EXISTS idempotency_key")
    op.execute("DROP TABLE IF EXISTS inbox")
    op.execute("DROP PUBLICATION IF EXISTS outbox_pub")
    op.execute("DROP TABLE IF EXISTS outbox")
