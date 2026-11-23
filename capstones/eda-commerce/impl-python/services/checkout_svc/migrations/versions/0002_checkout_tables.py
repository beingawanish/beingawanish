"""checkout-svc private tables: cart, cart_line, checkout, catalog_view.

Revision ID: 0002
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE cart (
    cart_id     text        PRIMARY KEY,
    customer_id text        NOT NULL,
    status      text        NOT NULL CHECK (status IN ('OPEN', 'CHECKED_OUT', 'ABANDONED')),
    currency    text        NOT NULL,
    version     bigint      NOT NULL,
    created_at  timestamptz NOT NULL,
    updated_at  timestamptz NOT NULL
)""")
    op.execute("""
CREATE TABLE cart_line (
    cart_id  text NOT NULL REFERENCES cart (cart_id),
    sku      text NOT NULL,
    quantity int  NOT NULL CHECK (quantity BETWEEN 1 AND 99),
    position int  NOT NULL,
    PRIMARY KEY (cart_id, sku)
)""")
    op.execute("""
CREATE TABLE checkout (
    checkout_id  text        PRIMARY KEY,
    order_id     text        NOT NULL UNIQUE,
    cart_id      text        NOT NULL UNIQUE REFERENCES cart (cart_id),
    customer_id  text        NOT NULL,
    total_minor  bigint      NOT NULL,
    currency     text        NOT NULL,
    order_status text        NOT NULL,
    created_at   timestamptz NOT NULL
)""")
    op.execute("""
CREATE TABLE catalog_view (
    sku             text        PRIMARY KEY,
    name            text,
    status          text,
    product_version bigint,
    list_minor      bigint,
    sale_minor      bigint,
    currency        text,
    priced_as_of    timestamptz,
    price_version   bigint,
    available       int,
    stock_version   bigint,
    updated_at      timestamptz NOT NULL DEFAULT now()
)""")


def downgrade() -> None:
    for t in ("catalog_view", "checkout", "cart_line", "cart"):
        op.execute(f"DROP TABLE IF EXISTS {t}")
