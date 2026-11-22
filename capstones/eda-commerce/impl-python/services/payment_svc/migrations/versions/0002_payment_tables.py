"""payment-svc private tables: payment, payment_attempt, refund, psp_webhook.

Revision ID: 0002
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE payment (
    payment_id               text        PRIMARY KEY,
    order_id                 text        NOT NULL,
    customer_id              text        NOT NULL,
    amount_minor             bigint      NOT NULL,
    currency                 text        NOT NULL,
    status                   text        NOT NULL,
    psp_payment_id           text,
    psp_reference            text,
    decline_reason           text,
    capture_failure          text,
    authorized_at            timestamptz,
    authorization_expires_at timestamptz,
    declined_at              timestamptz,
    captured_at              timestamptz,
    capture_failed_at        timestamptz,
    voided_at                timestamptz,
    unknown_since            timestamptz,
    next_reconcile_at        timestamptz,
    late_success_voided      boolean     NOT NULL DEFAULT false,
    last_command_id          text,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("CREATE INDEX payment_reconcile_idx ON payment (next_reconcile_at) WHERE status = 'UNKNOWN'")
    op.execute("CREATE INDEX payment_order_idx ON payment (order_id)")
    op.execute("""
CREATE TABLE payment_attempt (
    id         bigserial   PRIMARY KEY,
    payment_id text        NOT NULL,
    operation  text        NOT NULL,
    outcome    text        NOT NULL,
    detail     text,
    at         timestamptz NOT NULL
)""")
    op.execute("CREATE INDEX payment_attempt_payment_idx ON payment_attempt (payment_id)")
    op.execute("""
CREATE TABLE refund (
    refund_id       text        PRIMARY KEY,
    payment_id      text        NOT NULL,
    order_id        text        NOT NULL,
    return_id       text,
    amount_minor    bigint      NOT NULL,
    currency        text        NOT NULL,
    status          text        NOT NULL,
    psp_reference   text,
    failure_reason  text,
    retryable       boolean     NOT NULL DEFAULT false,
    finished_at     timestamptz,
    last_command_id text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("""
CREATE TABLE psp_webhook (
    psp_event_id       text        PRIMARY KEY,
    event_type         text        NOT NULL,
    merchant_reference text        NOT NULL,
    payload            jsonb       NOT NULL,
    received_at        timestamptz NOT NULL DEFAULT now(),
    processed_at       timestamptz
)""")
    op.execute("CREATE INDEX psp_webhook_unprocessed_idx ON psp_webhook (received_at) WHERE processed_at IS NULL")


def downgrade() -> None:
    for t in ("psp_webhook", "refund", "payment_attempt", "payment"):
        op.execute(f"DROP TABLE IF EXISTS {t}")
