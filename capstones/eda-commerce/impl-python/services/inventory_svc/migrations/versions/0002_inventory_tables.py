"""inventory-svc private tables: stock, reservation, reservation_line, restock.

Revision ID: 0002
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE stock (
    sku         text        PRIMARY KEY,
    on_hand     int         NOT NULL CHECK (on_hand >= 0),
    reserved    int         NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    version     bigint      NOT NULL DEFAULT 0,
    updated_at  timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("""
CREATE TABLE reservation (
    reservation_id text        PRIMARY KEY,
    order_id       text        NOT NULL,
    status         text        NOT NULL CHECK (status IN ('HELD','COMMITTED','RELEASED','EXPIRED','REJECTED')),
    expires_at     timestamptz,
    shortages      jsonb       NOT NULL DEFAULT '[]'::jsonb,
    reason         text,
    changed_at     timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("CREATE INDEX reservation_held_expiry_idx ON reservation (expires_at) WHERE status = 'HELD'")
    op.execute("CREATE INDEX reservation_order_idx ON reservation (order_id)")
    op.execute("""
CREATE TABLE reservation_line (
    reservation_id text NOT NULL REFERENCES reservation (reservation_id),
    sku            text NOT NULL,
    quantity       int  NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (reservation_id, sku)
)""")
    op.execute("""
CREATE TABLE restock (
    restock_id   text        PRIMARY KEY,
    order_id     text        NOT NULL,
    return_id    text        NOT NULL,
    lines        jsonb       NOT NULL,
    restocked_at timestamptz NOT NULL
)""")


def downgrade() -> None:
    for t in ("restock", "reservation_line", "reservation", "stock"):
        op.execute(f"DROP TABLE IF EXISTS {t}")
