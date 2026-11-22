"""order-svc write model: orders, order_line, invoice, invoice_counter.

Revision ID: 0002
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE orders (
    order_id        text        PRIMARY KEY,
    customer_id     text        NOT NULL,
    status          text        NOT NULL,
    total_minor     bigint      NOT NULL,
    currency        text        NOT NULL,
    placed_at       timestamptz NOT NULL,
    version         bigint      NOT NULL DEFAULT 0,
    contact_email   text        NOT NULL,
    ship_to         jsonb       NOT NULL,
    shipping_method text        NOT NULL,
    updated_at      timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("CREATE INDEX orders_customer_idx ON orders (customer_id, placed_at DESC)")
    op.execute("""
CREATE TABLE order_line (
    order_id         text   NOT NULL REFERENCES orders (order_id),
    line_id          text   NOT NULL,
    position         int    NOT NULL,
    sku              text   NOT NULL,
    product_name     text   NOT NULL,
    quantity         int    NOT NULL,
    unit_price_minor bigint NOT NULL,
    line_total_minor bigint NOT NULL,
    PRIMARY KEY (order_id, line_id)
)""")
    op.execute("""
CREATE TABLE invoice (
    invoice_id  text        PRIMARY KEY,
    order_id    text        NOT NULL UNIQUE,
    number      text        NOT NULL UNIQUE,
    total_minor bigint      NOT NULL,
    currency    text        NOT NULL,
    document    jsonb       NOT NULL,
    issued_at   timestamptz NOT NULL
)""")
    op.execute("CREATE TABLE invoice_counter (year int PRIMARY KEY, last_seq bigint NOT NULL)")


def downgrade() -> None:
    for t in ("invoice_counter", "invoice", "order_line", "orders"):
        op.execute(f"DROP TABLE IF EXISTS {t}")
