"""returns-svc private tables: eligibility_view (projection of order events), return_request,
return_line, rma_counter.

``eligibility_view.ship_to`` is the pickup address for the return label (personal data, ADR-0013).
``rma_counter`` makes RMA numbers gapless per year, like invoice numbers (guide §6.2).

Revision ID: 0002
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE eligibility_view (
    order_id               text        PRIMARY KEY,
    customer_id            text        NOT NULL,
    currency               text        NOT NULL,
    total_minor            bigint      NOT NULL,
    shipping_fee_minor     bigint      NOT NULL DEFAULT 0,
    lines                  jsonb       NOT NULL,
    ship_to                jsonb,
    payment_id             text,
    warehouse_id           text,
    delivered_at           timestamptz,
    cancelled              boolean     NOT NULL DEFAULT false,
    shipping_fee_return_id text,
    updated_at             timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("""
CREATE TABLE return_request (
    return_id            text        PRIMARY KEY,
    order_id             text        NOT NULL REFERENCES eligibility_view (order_id),
    customer_id          text        NOT NULL,
    reason               text        NOT NULL,
    comment              text,
    status               text        NOT NULL,
    rma_number           text        UNIQUE,
    currency             text        NOT NULL,
    refund_minor         bigint,
    refund_id            text        UNIQUE,
    label                jsonb,
    parcel_due_by        timestamptz,
    counts_against_order boolean     NOT NULL DEFAULT true,
    requested_at         timestamptz NOT NULL,
    updated_at           timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("CREATE INDEX return_request_order_idx ON return_request (order_id)")
    op.execute("""
CREATE TABLE return_line (
    return_id          text   NOT NULL REFERENCES return_request (return_id),
    line_id            text   NOT NULL,
    sku                text   NOT NULL,
    quantity           int    NOT NULL CHECK (quantity > 0),
    unit_price_minor   bigint NOT NULL,
    inspection         jsonb,
    PRIMARY KEY (return_id, line_id)
)""")
    op.execute("""
CREATE TABLE rma_counter (
    year      int    PRIMARY KEY,
    last_seq  bigint NOT NULL
)""")


def downgrade() -> None:
    for t in ("return_line", "return_request", "rma_counter", "eligibility_view"):
        op.execute(f"DROP TABLE IF EXISTS {t}")
