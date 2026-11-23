"""Shared tables of contracts/sql/common-tables.sql (outbox, inbox, idempotency_key, saga_instance, saga_transition).

Revision ID: 0001
"""

from alembic import op
from edacommon.migrations.common_tables import downgrade_common, upgrade_common

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_common(op, saga=True)


def downgrade() -> None:
    downgrade_common(op, saga=True)
