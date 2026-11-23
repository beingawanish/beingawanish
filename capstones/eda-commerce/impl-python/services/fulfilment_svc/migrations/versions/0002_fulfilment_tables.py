"""fulfilment-svc private tables: fulfilment, parcel, return_intake.

``fulfilment.ship_to`` holds the ship-to address (personal data, ADR-0013): the warehouse needs it to
put it on ``OrderPacked``. It is the only PII column and is dropped by the retention job once the
fulfilment is dispatched or cancelled for more than 90 days (not built in this template).

Revision ID: 0002
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE fulfilment (
    fulfilment_id         text        PRIMARY KEY,
    order_id              text        NOT NULL,
    status                text        NOT NULL CHECK (status IN
                              ('REQUESTED','ACCEPTED','PICKED','PACKED','DISPATCHED','CANCELLED','FAILED')),
    lines                 jsonb       NOT NULL DEFAULT '[]'::jsonb,
    ship_to               jsonb,
    shipping_method       text        NOT NULL DEFAULT 'STANDARD',
    attempt               int         NOT NULL DEFAULT 1,
    wms_submissions       int         NOT NULL DEFAULT 0,
    warehouse_id          text,
    accepted_at           timestamptz,
    estimated_dispatch_at timestamptz,
    picked_at             timestamptz,
    packed_at             timestamptz,
    dispatched_at         timestamptz,
    cancelled_at          timestamptz,
    failed_at             timestamptz,
    failure_reason        text,
    failure_detail        text,
    manifest              jsonb,
    shipment_id           text,
    last_command_id       text,
    correlation_id        text        NOT NULL,
    version               bigint      NOT NULL DEFAULT 0,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("CREATE INDEX fulfilment_order_idx ON fulfilment (order_id)")
    op.execute("""
CREATE TABLE parcel (
    parcel_id     text PRIMARY KEY,
    fulfilment_id text NOT NULL REFERENCES fulfilment (fulfilment_id),
    weight_grams  int  NOT NULL CHECK (weight_grams > 0),
    length_mm     int  NOT NULL,
    width_mm      int  NOT NULL,
    height_mm     int  NOT NULL
)""")
    op.execute("CREATE INDEX parcel_fulfilment_idx ON parcel (fulfilment_id)")
    op.execute("""
CREATE TABLE return_intake (
    return_id         text        PRIMARY KEY,
    order_id          text        NOT NULL,
    rma_number        text        NOT NULL,
    status            text        NOT NULL CHECK (status IN ('EXPECTED','RECEIVED','INSPECTED')),
    lines             jsonb       NOT NULL,
    expected_by       timestamptz NOT NULL,
    shipment_id       text,
    received_at       timestamptz,
    received_event_id text,
    results           jsonb,
    inspected_at      timestamptz,
    correlation_id    text        NOT NULL,
    version           bigint      NOT NULL DEFAULT 0,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("CREATE INDEX return_intake_order_idx ON return_intake (order_id)")


def downgrade() -> None:
    for t in ("parcel", "return_intake", "fulfilment"):
        op.execute(f"DROP TABLE IF EXISTS {t}")
