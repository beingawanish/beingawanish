"""catalog-svc private tables: product, price, stock_level_view.

Revision ID: 0002
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE product (
    sku           text        PRIMARY KEY,
    name          text        NOT NULL,
    description   text,
    brand         text,
    category_path jsonb       NOT NULL DEFAULT '[]'::jsonb,
    attributes    jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status        text        NOT NULL CHECK (status IN ('ACTIVE', 'DISCONTINUED')),
    weight_grams  int,
    image_urls    jsonb       NOT NULL DEFAULT '[]'::jsonb,
    version       bigint      NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("""
CREATE TABLE price (
    sku           text        PRIMARY KEY REFERENCES product (sku),
    price_list_id text        NOT NULL,
    list_minor    bigint      NOT NULL,
    sale_minor    bigint,
    currency      text        NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("""
CREATE TABLE stock_level_view (
    sku       text        PRIMARY KEY,
    available int         NOT NULL,
    version   bigint      NOT NULL,
    as_of     timestamptz NOT NULL
)""")


def downgrade() -> None:
    for t in ("stock_level_view", "price", "product"):
        op.execute(f"DROP TABLE IF EXISTS {t}")
