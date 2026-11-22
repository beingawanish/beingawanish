-- inventory-svc private tables (ADR-0016). V1 is contracts/sql/common-tables.sql.
CREATE TABLE stock (
    sku         text        PRIMARY KEY,
    on_hand     int         NOT NULL CHECK (on_hand >= 0),
    reserved    int         NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    version     bigint      NOT NULL DEFAULT 0,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT stock_reserved_within_on_hand CHECK (reserved <= on_hand)
);

CREATE TABLE reservation (
    reservation_id  text        PRIMARY KEY,
    order_id        text        NOT NULL,
    status          text        NOT NULL CHECK (status IN ('HELD', 'COMMITTED', 'RELEASED', 'EXPIRED', 'REJECTED')),
    expires_at      timestamptz NOT NULL,
    release_reason  text,
    shortages       jsonb,
    changed_at      timestamptz NOT NULL,
    version         bigint      NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now()
);
-- The TTL sweeper scans held reservations by expiry.
CREATE INDEX reservation_held_expiry_idx ON reservation (expires_at) WHERE status = 'HELD';
CREATE INDEX reservation_order_idx ON reservation (order_id);

CREATE TABLE reservation_line (
    reservation_id  text NOT NULL REFERENCES reservation (reservation_id),
    sku             text NOT NULL,
    quantity        int  NOT NULL CHECK (quantity > 0)
);
CREATE INDEX reservation_line_reservation_idx ON reservation_line (reservation_id);

CREATE TABLE restock (
    restock_id    text        PRIMARY KEY,
    order_id      text        NOT NULL,
    return_id     text        NOT NULL,
    lines         jsonb       NOT NULL,
    restocked_at  timestamptz NOT NULL
);
