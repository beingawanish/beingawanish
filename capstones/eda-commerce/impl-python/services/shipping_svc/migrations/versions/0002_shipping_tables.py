"""shipping-svc private tables: shipment, tracking_event.

``shipment.address`` is the address printed on the label (ship-to for outbound, pickup for returns):
personal data (ADR-0013), kept only because a booking retry needs it again.
``tracking_event`` keeps every raw carrier webhook for audit, including the ones that were not
emitted because they were duplicates or moved backwards (architecture §5.10).

Revision ID: 0002
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE shipment (
    shipment_id      text        PRIMARY KEY,
    order_id         text        NOT NULL,
    direction        text        NOT NULL CHECK (direction IN ('OUTBOUND','RETURN')),
    fulfilment_id    text        UNIQUE,
    return_id        text        UNIQUE,
    warehouse_id     text,
    address          jsonb       NOT NULL,
    parcel_count     int         NOT NULL DEFAULT 1,
    shipping_method  text        NOT NULL DEFAULT 'STANDARD',
    status           text        NOT NULL CHECK (status IN ('BOOKING_PENDING','BOOKED','BOOKING_FAILED')),
    carrier          text,
    tracking_number  text        UNIQUE,
    label            jsonb,
    booking_attempts int         NOT NULL DEFAULT 0,
    next_attempt_at  timestamptz,
    booked_at        timestamptz,
    tracking_rank    int         NOT NULL DEFAULT 0,
    delivered_at     timestamptz,
    correlation_id   text        NOT NULL,
    causation_id     text,
    version          bigint      NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("CREATE INDEX shipment_order_idx ON shipment (order_id)")
    op.execute("CREATE INDEX shipment_booking_due_idx ON shipment (next_attempt_at) WHERE status = 'BOOKING_PENDING'")
    op.execute("""
CREATE TABLE tracking_event (
    carrier_event_id text        PRIMARY KEY,
    tracking_number  text        NOT NULL,
    status           text        NOT NULL,
    exception_code   text,
    location         text,
    occurred_at      timestamptz NOT NULL,
    payload          jsonb       NOT NULL,
    received_at      timestamptz NOT NULL DEFAULT now(),
    processed_at     timestamptz,
    outcome          text,
    shipment_id      text
)""")
    op.execute("CREATE INDEX tracking_event_unprocessed_idx ON tracking_event (received_at) WHERE processed_at IS NULL")
    op.execute("CREATE INDEX tracking_event_tracking_idx ON tracking_event (tracking_number, occurred_at)")


def downgrade() -> None:
    for t in ("tracking_event", "shipment"):
        op.execute(f"DROP TABLE IF EXISTS {t}")
