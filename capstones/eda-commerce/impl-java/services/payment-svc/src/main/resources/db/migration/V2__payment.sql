-- payment-svc private tables. V1 is contracts/sql/common-tables.sql.
CREATE TABLE payment (
    payment_id                   text        PRIMARY KEY,   -- minted by order-svc; PSP idempotency key
    order_id                     text        NOT NULL,
    customer_id                  text        NOT NULL,
    amount_minor                 bigint      NOT NULL,
    currency                     text        NOT NULL,
    payment_method_token         text        NOT NULL,      -- PSP token only, never card data (ADR-0013)
    status                       text        NOT NULL,
    psp_reference                text,
    decline_reason               text,
    authorized_at                timestamptz,
    authorization_expires_at     timestamptz,
    capture_failure_auth_expired boolean     NOT NULL DEFAULT false,
    capture_failure_retryable    boolean     NOT NULL DEFAULT false,
    changed_at                   timestamptz NOT NULL,
    reconcile_deadline           timestamptz,
    next_reconcile_at            timestamptz,
    late_success_voided          boolean     NOT NULL DEFAULT false,
    version                      bigint      NOT NULL DEFAULT 1
);
CREATE INDEX payment_reconcile_idx ON payment (next_reconcile_at) WHERE status IN ('PENDING', 'UNKNOWN');
CREATE INDEX payment_order_idx ON payment (order_id);

CREATE TABLE payment_attempt (
    id          bigserial   PRIMARY KEY,
    payment_id  text        NOT NULL,
    operation   text        NOT NULL,
    outcome     text        NOT NULL,
    at          timestamptz NOT NULL
);
CREATE INDEX payment_attempt_payment_idx ON payment_attempt (payment_id);

CREATE TABLE refund (
    refund_id       text        PRIMARY KEY,   -- minted by returns-svc; PSP idempotency key
    payment_id      text        NOT NULL REFERENCES payment (payment_id),
    order_id        text        NOT NULL,
    return_id       text,
    amount_minor    bigint      NOT NULL,
    currency        text        NOT NULL,
    reason          text        NOT NULL,
    status          text        NOT NULL,
    psp_reference   text,
    failure_reason  text,
    retryable       boolean     NOT NULL DEFAULT false,
    changed_at      timestamptz NOT NULL
);

-- Raw PSP webhooks (store-then-ack). The inbox row (consumer 'psp-webhook') deduplicates.
CREATE TABLE psp_webhook (
    psp_event_id        text        PRIMARY KEY,
    event_type          text        NOT NULL,
    merchant_reference  text        NOT NULL,
    psp_payment_id      text,
    failure_code        text,
    payload             bytea       NOT NULL,
    received_at         timestamptz NOT NULL DEFAULT now(),
    processed_at        timestamptz
);
CREATE INDEX psp_webhook_unprocessed_idx ON psp_webhook (received_at) WHERE processed_at IS NULL;
