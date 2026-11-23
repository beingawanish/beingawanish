-- fulfilment-svc private tables (architecture §3). V1 is contracts/sql/common-tables.sql.
-- One row per fulfilmentId (minted by order-svc). ship_to is personal data: it is needed for the
-- OrderPacked hand-off to shipping and is never logged.
CREATE TABLE fulfilment (
    fulfilment_id          text        PRIMARY KEY,
    order_id               text        NOT NULL,
    status                 text        NOT NULL CHECK (status IN ('REQUESTED', 'ACCEPTED', 'PICKED', 'PACKED', 'DISPATCHED', 'CANCELLED', 'FAILED')),
    attempt                int         NOT NULL DEFAULT 1,
    lines                  jsonb       NOT NULL,
    ship_to                jsonb,
    shipping_method        text        NOT NULL,
    warehouse_id           text,
    estimated_dispatch_at  timestamptz,
    manifest               jsonb,
    shipment_id            text,
    failure_reason         text,
    failure_detail         text,
    accepted_version       bigint,
    accepted_at            timestamptz,
    picked_at              timestamptz,
    packed_at              timestamptz,
    dispatched_at          timestamptz,
    cancelled_at           timestamptz,
    failed_at              timestamptz,
    version                bigint      NOT NULL DEFAULT 0,
    created_at             timestamptz NOT NULL,
    updated_at             timestamptz NOT NULL
);
CREATE INDEX fulfilment_order_idx ON fulfilment (order_id);

CREATE TABLE parcel (
    parcel_id      text PRIMARY KEY,
    fulfilment_id  text NOT NULL REFERENCES fulfilment (fulfilment_id),
    weight_grams   int  NOT NULL,
    length_mm      int  NOT NULL,
    width_mm       int  NOT NULL,
    height_mm      int  NOT NULL
);
CREATE INDEX parcel_fulfilment_idx ON parcel (fulfilment_id);

CREATE TABLE return_intake (
    return_id     text        PRIMARY KEY,
    order_id      text        NOT NULL,
    rma_number    text        NOT NULL,
    status        text        NOT NULL CHECK (status IN ('EXPECTED', 'RECEIVED', 'INSPECTED')),
    lines         jsonb       NOT NULL,
    expected_by   timestamptz NOT NULL,
    received_at   timestamptz,
    results       jsonb,
    inspected_at  timestamptz,
    version       bigint      NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL,
    updated_at    timestamptz NOT NULL
);
CREATE INDEX return_intake_order_idx ON return_intake (order_id);
