-- shipping-svc private tables (architecture §3). V1 is contracts/sql/common-tables.sql.
-- One shipment per outbound fulfilment (shipmentId minted here) or per return label (shipmentId
-- minted by the returns saga). address is personal data, needed for the booking; never logged.
CREATE TABLE shipment (
    shipment_id      text        PRIMARY KEY,
    order_id         text        NOT NULL,
    direction        text        NOT NULL CHECK (direction IN ('OUTBOUND', 'RETURN')),
    fulfilment_id    text        UNIQUE,
    return_id        text,
    warehouse_id     text,
    address          jsonb       NOT NULL,
    parcel_count     int         NOT NULL DEFAULT 1,
    shipping_method  text        NOT NULL,
    status           text        NOT NULL CHECK (status IN ('BOOKING_PENDING', 'BOOKED', 'BOOKING_FAILED')),
    carrier          text,
    tracking_number  text        UNIQUE,
    label            jsonb,
    booking_attempts int         NOT NULL DEFAULT 0,
    next_attempt_at  timestamptz,
    booked_at        timestamptz,
    tracking_rank    int         NOT NULL DEFAULT 0,
    delivered_at     timestamptz,
    created_version  bigint      NOT NULL DEFAULT 0,
    correlation_id   text        NOT NULL,
    causation_id     text,
    version          bigint      NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL,
    updated_at       timestamptz NOT NULL
);
CREATE INDEX shipment_order_idx ON shipment (order_id);
CREATE INDEX shipment_booking_due_idx ON shipment (next_attempt_at) WHERE status = 'BOOKING_PENDING';

-- Every raw carrier webhook, kept for audit (architecture §5.10), applied after the 200 was sent
-- (store-then-ack, webhooks.yaml rule 3).
CREATE TABLE tracking_event (
    carrier_event_id  text        PRIMARY KEY,
    tracking_number   text        NOT NULL,
    status            text        NOT NULL,
    exception_code    text,
    location          text,
    occurred_at       timestamptz NOT NULL,
    received_at       timestamptz NOT NULL,
    raw               bytea       NOT NULL,
    processed_at      timestamptz,
    outcome           text
);
CREATE INDEX tracking_event_unprocessed_idx ON tracking_event (occurred_at) WHERE processed_at IS NULL;
CREATE INDEX tracking_event_tracking_idx ON tracking_event (tracking_number, occurred_at);
