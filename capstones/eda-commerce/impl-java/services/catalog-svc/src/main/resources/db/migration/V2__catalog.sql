-- catalog-svc private tables. V1 is contracts/sql/common-tables.sql.
CREATE TABLE product (
    sku            text        PRIMARY KEY,
    name           text        NOT NULL,
    description    text,
    brand          text,
    category_path  jsonb       NOT NULL DEFAULT '[]',
    attributes     jsonb       NOT NULL DEFAULT '{}',
    status         text        NOT NULL CHECK (status IN ('ACTIVE', 'DISCONTINUED')),
    weight_grams   int,
    image_urls     jsonb       NOT NULL DEFAULT '[]',
    version        bigint      NOT NULL,     -- aggregateVersion of ProductUpserted
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX product_category_idx ON product USING gin (category_path);

CREATE TABLE price (
    sku               text        PRIMARY KEY REFERENCES product (sku),
    price_list_id     text        NOT NULL,
    list_price_minor  bigint      NOT NULL CHECK (list_price_minor >= 0),
    sale_price_minor  bigint      CHECK (sale_price_minor >= 0),
    currency          text        NOT NULL,
    valid_from        timestamptz NOT NULL DEFAULT now(),
    version           bigint      NOT NULL      -- aggregateVersion of PriceChanged
);

-- Projection of inventory.stock-level.v1 (advisory availability).
CREATE TABLE stock_level_view (
    sku        text        PRIMARY KEY,
    on_hand    int         NOT NULL,
    reserved   int         NOT NULL,
    available  int         NOT NULL,
    version    bigint      NOT NULL,
    as_of      timestamptz NOT NULL
);
