"""DDL of the order-history read model. Parameterised by schema name so a rebuild can project into
``order_history_v2`` next to the live one, then switch reads (ADR-0010 "Rebuilds")."""

from __future__ import annotations

import re


def ddl(schema: str) -> list[str]:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
        raise ValueError(f"bad schema name {schema!r}")
    return [
        f"CREATE SCHEMA IF NOT EXISTS {schema}",
        f"""CREATE TABLE {schema}.order_summary (
    order_id            text        PRIMARY KEY,
    customer_id         text        NOT NULL,
    status              text        NOT NULL,
    total_minor         bigint      NOT NULL,
    currency            text        NOT NULL,
    item_count          int         NOT NULL,
    placed_at           timestamptz NOT NULL,
    version             bigint      NOT NULL,
    cancellation_reason text,
    carrier             text,
    tracking_number     text,
    shipment_status     text,
    invoice_available   boolean     NOT NULL DEFAULT false,
    refunded_minor      bigint      NOT NULL DEFAULT 0
)""",
        f"CREATE INDEX order_summary_customer_idx ON {schema}.order_summary (customer_id, placed_at DESC, order_id DESC)",
        f"""CREATE TABLE {schema}.order_line (
    order_id          text   NOT NULL,
    line_id           text   NOT NULL,
    position          int    NOT NULL,
    sku               text   NOT NULL,
    product_name      text   NOT NULL,
    quantity          int    NOT NULL,
    unit_price_minor  bigint NOT NULL,
    line_total_minor  bigint NOT NULL,
    returned_quantity int    NOT NULL DEFAULT 0,
    PRIMARY KEY (order_id, line_id)
)""",
        f"""CREATE TABLE {schema}.timeline (
    order_id    text        NOT NULL,
    event_id    text        NOT NULL,
    at          timestamptz NOT NULL,
    kind        text        NOT NULL,
    description text,
    PRIMARY KEY (order_id, event_id)
)""",
    ]
