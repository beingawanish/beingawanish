"""CQRS read model schema ``order_history`` (ADR-0010), owned by the order-history-projector.

Revision ID: 0003
"""

from alembic import op
from order_svc.adapters.projector.schema import ddl

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in ddl("order_history"):
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS order_history CASCADE")
