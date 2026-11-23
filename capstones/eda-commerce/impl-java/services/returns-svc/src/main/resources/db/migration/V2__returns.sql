-- returns-svc private tables (architecture §3). V1 is contracts/sql/common-tables.sql; the saga
-- itself lives in the shared saga_instance / saga_transition tables.

-- Projection of order.events.v1 (and the warehouse from fulfilment.events.v1) used to answer
-- POST /returns synchronously. pickup_address is personal data, needed for the return label.
CREATE TABLE eligibility_view (
    order_id            text        PRIMARY KEY,
    customer_id         text        NOT NULL,
    status              text        NOT NULL CHECK (status IN ('PLACED', 'CONFIRMED', 'DELIVERED', 'CANCELLED')),
    payment_id          text,
    currency            text        NOT NULL,
    lines               jsonb       NOT NULL,
    shipping_fee_minor  bigint      NOT NULL DEFAULT 0,
    pickup_address      jsonb       NOT NULL,
    warehouse_id        text,
    delivered_at        timestamptz,
    window_ends_at      timestamptz,
    version             bigint      NOT NULL,
    updated_at          timestamptz NOT NULL
);

-- The query side of each return, written in the same transaction as every saga transition.
CREATE TABLE return_request (
    return_id            text        PRIMARY KEY,
    order_id             text        NOT NULL,
    customer_id          text        NOT NULL,
    rma_number           text        UNIQUE,
    saga_state           text        NOT NULL,
    status               text        NOT NULL,
    reason               text        NOT NULL,
    comment              text,
    refund_amount_minor  bigint,
    currency             text        NOT NULL,
    label                jsonb,
    parcel_due_by        timestamptz,
    -- false once the return ended without the parcel coming back (expired, rejected in review):
    -- its quantities can be returned again.
    holds_quantity       boolean     NOT NULL DEFAULT true,
    requested_at         timestamptz NOT NULL,
    updated_at           timestamptz NOT NULL
);
CREATE INDEX return_request_order_idx ON return_request (order_id);

CREATE TABLE return_line (
    return_id           text NOT NULL REFERENCES return_request (return_id),
    seq                 int  NOT NULL,
    line_id             text NOT NULL,
    sku                 text NOT NULL,
    quantity            int  NOT NULL CHECK (quantity > 0),
    inspection_outcome  text,
    PRIMARY KEY (return_id, seq)
);

-- Gapless RMA numbers per year (RMA-2026-000042), like invoice numbers (guide §6.2).
CREATE TABLE rma_counter (
    year        int    PRIMARY KEY,
    last_value  bigint NOT NULL
);
