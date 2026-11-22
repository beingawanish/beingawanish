-- The order-history read model (ADR-0010), written by the projector process, read by the API.
-- Disposable: rebuild into a new schema from offset 0 with a new consumer group.
CREATE SCHEMA IF NOT EXISTS order_history;

CREATE TABLE order_history.order_summary (
    order_id             text        PRIMARY KEY,
    customer_id          text        NOT NULL,
    status               text        NOT NULL,
    total_minor          bigint      NOT NULL,
    currency             text        NOT NULL,
    item_count           int         NOT NULL,
    placed_at            timestamptz NOT NULL,
    version              bigint      NOT NULL,          -- aggregateVersion of the last order event applied
    cancellation_reason  text,
    carrier              text,
    tracking_number      text,
    shipment_status      text,
    shipment_rank        int         NOT NULL DEFAULT 0,
    invoice_available    boolean     NOT NULL DEFAULT false,
    refunded_minor       bigint      NOT NULL DEFAULT 0,
    updated_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX order_summary_customer_idx ON order_history.order_summary (customer_id, placed_at DESC, order_id DESC);

CREATE TABLE order_history.order_line (
    order_id           text   NOT NULL,
    line_id            text   NOT NULL,
    sku                text   NOT NULL,
    product_name       text   NOT NULL,
    quantity           int    NOT NULL,
    unit_price_minor   bigint NOT NULL,
    line_total_minor   bigint NOT NULL,
    currency           text   NOT NULL,
    returned_quantity  int    NOT NULL DEFAULT 0,
    PRIMARY KEY (order_id, line_id)
);

CREATE TABLE order_history.timeline (
    event_id     text        PRIMARY KEY,
    order_id     text        NOT NULL,
    at           timestamptz NOT NULL,
    kind         text        NOT NULL,
    description  text
);
CREATE INDEX timeline_order_idx ON order_history.timeline (order_id, at);
