"""Saga rows and transitions on the shared tables ``saga_instance`` / ``saga_transition``."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from edacommon.db import saga_instance_table as si
from edacommon.db import saga_transition_table as st
from edacommon.errors import Transient

TRIGGER_DEADLINE = "DEADLINE"
TRIGGER_OPERATOR = "OPERATOR"


class ConcurrentSagaUpdate(Transient):
    """Another transaction changed the saga first. Transient: re-read and re-apply in place."""


@dataclass(frozen=True, slots=True)
class SagaRow:
    saga_id: str
    saga_type: str
    state: str
    data: dict[str, Any]
    version: int
    deadline_at: datetime | None
    step_attempts: int
    correlation_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None

    def evolve(self, **kw: Any) -> SagaRow:
        return replace(self, **kw)


def _row(m: Any) -> SagaRow:
    return SagaRow(
        saga_id=m["saga_id"],
        saga_type=m["saga_type"],
        state=m["state"],
        data=dict(m["data"]),
        version=int(m["version"]),
        deadline_at=m["deadline_at"],
        step_attempts=int(m["step_attempts"]),
        correlation_id=m["correlation_id"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
        completed_at=m["completed_at"],
    )


@dataclass(frozen=True, slots=True)
class TransitionRow:
    seq: int
    from_state: str
    to_state: str
    trigger_type: str
    trigger_id: str | None
    at: datetime


class SagaRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, saga_id: str) -> SagaRow | None:
        m = self._s.execute(select(si).where(si.c.saga_id == saga_id)).mappings().first()
        return _row(m) if m else None

    def load_for_update(self, saga_id: str, *, skip_locked: bool = False) -> SagaRow | None:
        q = select(si).where(si.c.saga_id == saga_id).with_for_update(skip_locked=skip_locked)
        m = self._s.execute(q).mappings().first()
        return _row(m) if m else None

    def insert(self, row: SagaRow, now: datetime) -> None:
        self._s.execute(
            insert(si).values(
                saga_id=row.saga_id,
                saga_type=row.saga_type,
                state=row.state,
                data=row.data,
                version=row.version,
                deadline_at=row.deadline_at,
                step_attempts=row.step_attempts,
                correlation_id=row.correlation_id,
                created_at=now,
                updated_at=now,
                completed_at=row.completed_at,
            )
        )

    def save(self, row: SagaRow, *, expected_version: int, now: datetime) -> None:
        res = self._s.execute(
            update(si)
            .where(si.c.saga_id == row.saga_id, si.c.version == expected_version)
            .values(
                state=row.state,
                data=row.data,
                version=row.version,
                deadline_at=row.deadline_at,
                step_attempts=row.step_attempts,
                updated_at=now,
                completed_at=row.completed_at,
            )
        )
        if res.rowcount != 1:  # type: ignore[attr-defined]
            raise ConcurrentSagaUpdate(f"saga {row.saga_id} changed concurrently (expected v{expected_version})")

    def append_transition(
        self, *, saga_id: str, seq: int, from_state: str, to_state: str, trigger_type: str, trigger_id: str | None, at: datetime
    ) -> None:
        self._s.execute(
            insert(st).values(
                saga_id=saga_id,
                seq=seq,
                from_state=from_state,
                to_state=to_state,
                trigger_type=trigger_type,
                trigger_id=trigger_id,
                at=at,
            )
        )

    def history(self, saga_id: str) -> list[TransitionRow]:
        rows = self._s.execute(select(st).where(st.c.saga_id == saga_id).order_by(st.c.seq)).mappings().all()
        return [
            TransitionRow(r["seq"], r["from_state"], r["to_state"], r["trigger_type"], r["trigger_id"], r["at"]) for r in rows
        ]

    def due_ids(self, saga_type: str, now: datetime, limit: int = 100) -> list[str]:
        return list(
            self._s.execute(
                select(si.c.saga_id)
                .where(si.c.saga_type == saga_type, si.c.deadline_at <= now)
                .order_by(si.c.deadline_at)
                .limit(limit)
            ).scalars()
        )

    def lock_if_due(self, saga_id: str, now: datetime) -> SagaRow | None:
        m = (
            self._s.execute(select(si).where(si.c.saga_id == saga_id, si.c.deadline_at <= now).with_for_update(skip_locked=True))
            .mappings()
            .first()
        )
        return _row(m) if m else None

    def count_overdue(self, saga_type: str, before: datetime) -> int:
        return int(
            self._s.execute(
                select(func.count()).select_from(si).where(si.c.saga_type == saga_type, si.c.deadline_at < before)
            ).scalar_one()
        )
