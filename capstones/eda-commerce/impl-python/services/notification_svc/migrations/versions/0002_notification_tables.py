"""notification-svc private tables: contact, order_contact, notification.

``contact`` and ``order_contact`` hold personal data (email, name): notification-svc owns contact
details for messaging (architecture §3) and learns them from ``OrderPlaced`` so that every other
event can carry ids only (ADR-0013). Erasure is this service's job once ``CustomerErased`` exists.
``notification.dedupe_key`` is the business-level guard: one message per template and business id,
even when a producer re-emits the same fact with a new eventId.

Revision ID: 0002
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE contact (
    customer_id text        PRIMARY KEY,
    email       text        NOT NULL,
    name        text,
    updated_at  timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("""
CREATE TABLE order_contact (
    order_id    text        PRIMARY KEY,
    customer_id text        NOT NULL,
    email       text        NOT NULL,
    name        text,
    created_at  timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("""
CREATE TABLE notification (
    notification_id     text        PRIMARY KEY,
    dedupe_key          text        NOT NULL UNIQUE,
    order_id            text,
    customer_id         text        NOT NULL,
    channel             text        NOT NULL,
    template            text        NOT NULL,
    source_event_id     text        NOT NULL,
    source_event_type   text        NOT NULL,
    attachment_count    int         NOT NULL DEFAULT 0,
    provider_message_id text,
    sent_at             timestamptz NOT NULL
)""")
    op.execute("CREATE INDEX notification_order_idx ON notification (order_id)")


def downgrade() -> None:
    for t in ("notification", "order_contact", "contact"):
        op.execute(f"DROP TABLE IF EXISTS {t}")
