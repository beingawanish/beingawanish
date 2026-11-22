-- order-svc private tables. V1 is contracts/sql/common-tables.sql.
CREATE TABLE orders (
    order_id              text        PRIMARY KEY,          -- minted by checkout-svc
    checkout_id           text        NOT NULL,
    customer_id           text        NOT NULL,
    status                text        NOT NULL,             -- customer-facing OrderStatus
    currency              text        NOT NULL,
    subtotal_minor        bigint      NOT NULL,
    shipping_fee_minor    bigint      NOT NULL,
    tax_minor             bigint      NOT NULL,
    total_minor           bigint      NOT NULL,
    shipping_address      jsonb       NOT NULL,             -- personal data (ADR-0013)
    contact_email         text        NOT NULL,             -- personal data
    shipping_method       text        NOT NULL,
    payment_method_token  text        NOT NULL,             -- PSP token, never card data
    placed_at             timestamptz NOT NULL,
    updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX orders_customer_idx ON orders (customer_id, placed_at DESC);

CREATE TABLE order_line (
    order_id          text   NOT NULL REFERENCES orders (order_id),
    line_id           text   NOT NULL,
    position          int    NOT NULL,
    sku               text   NOT NULL,
    product_name      text   NOT NULL,
    quantity          int    NOT NULL CHECK (quantity > 0),
    unit_price_minor  bigint NOT NULL,
    line_total_minor  bigint NOT NULL,
    PRIMARY KEY (order_id, line_id)
);

-- Gapless invoice numbers: one counter row per year, locked FOR UPDATE with the invoice insert.
CREATE TABLE invoice_counter (
    year         int    PRIMARY KEY,
    last_number  bigint NOT NULL
);

CREATE TABLE invoice (
    invoice_id      text        PRIMARY KEY,
    order_id        text        NOT NULL REFERENCES orders (order_id),
    invoice_number  text        NOT NULL UNIQUE,
    total_minor     bigint      NOT NULL,
    currency        text        NOT NULL,
    issued_at       timestamptz NOT NULL,
    bucket          text        NOT NULL,
    object_key      text        NOT NULL,
    size_bytes      bigint      NOT NULL,
    sha256          text        NOT NULL
);
CREATE INDEX invoice_order_idx ON invoice (order_id);
