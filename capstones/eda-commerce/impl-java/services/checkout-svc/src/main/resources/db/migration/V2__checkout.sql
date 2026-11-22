-- checkout-svc private tables. V1 is contracts/sql/common-tables.sql.
CREATE TABLE cart (
    cart_id      text        PRIMARY KEY,
    customer_id  text        NOT NULL,
    currency     text        NOT NULL,
    status       text        NOT NULL CHECK (status IN ('OPEN', 'CHECKED_OUT', 'ABANDONED')),
    version      bigint      NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE cart_line (
    cart_id   text NOT NULL REFERENCES cart (cart_id),
    sku       text NOT NULL,
    quantity  int  NOT NULL CHECK (quantity BETWEEN 1 AND 99),
    PRIMARY KEY (cart_id, sku)
);

CREATE TABLE checkout (
    checkout_id  text        PRIMARY KEY,
    order_id     text        NOT NULL UNIQUE,   -- minted here (architecture §3)
    cart_id      text        NOT NULL UNIQUE REFERENCES cart (cart_id),
    customer_id  text        NOT NULL,
    total_minor  bigint      NOT NULL,
    currency     text        NOT NULL,
    status       text        NOT NULL,          -- SUBMITTED, ORDER_PLACED, ORDER_CANCELLED
    created_at   timestamptz NOT NULL
);

-- Catalog read model from catalog.product.v1, catalog.price.v1, inventory.stock-level.v1 (ADR-0010).
CREATE TABLE catalog_view (
    sku               text        PRIMARY KEY,
    name              text,
    active            boolean     NOT NULL DEFAULT false,
    list_price_minor  bigint,
    sale_price_minor  bigint,
    currency          text,
    available         int,
    product_version   bigint      NOT NULL DEFAULT 0,
    price_version     bigint      NOT NULL DEFAULT 0,
    stock_version     bigint      NOT NULL DEFAULT 0,
    updated_at        timestamptz NOT NULL
);
