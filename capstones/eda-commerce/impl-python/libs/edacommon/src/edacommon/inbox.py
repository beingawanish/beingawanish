"""Idempotent-consumer inbox (ADR-0006).

``try_insert`` runs in the handler's transaction. ``ON CONFLICT DO NOTHING`` instead of catching a
unique violation keeps the transaction usable and avoids an aborted-transaction round trip.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from edacommon.db import inbox_table


def try_insert(
    session: Session,
    *,
    message_id: str,
    consumer: str,
    message_type: str,
    source_topic: str | None = None,
    source_partition: int | None = None,
    source_offset: int | None = None,
) -> bool:
    """Insert the inbox row. ``False`` means this consumer already processed the message."""
    stmt = (
        pg_insert(inbox_table)
        .values(
            message_id=message_id,
            consumer=consumer,
            message_type=message_type,
            source_topic=source_topic,
            source_partition=source_partition,
            source_offset=source_offset,
        )
        .on_conflict_do_nothing(index_elements=["message_id", "consumer"])
        .returning(inbox_table.c.message_id)
    )
    return session.execute(stmt).first() is not None
