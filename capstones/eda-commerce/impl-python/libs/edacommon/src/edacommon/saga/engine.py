"""Apply one saga transition per transaction (guide §4.2).

::

    handle(trigger) in one transaction:                  # the caller's unit of work
        saga  = repo.load_for_update(saga_id)
        step  = decide(saga, now)                        # application -> pure domain transition
        if step.ignored: return
        outbox.append(...) for each command and event    # key = saga.correlation key (orderId)
        repo.save(saga with new state, data, version+n, deadline, step_attempts)   # version check
        transitions.append(from, to, trigger_type, trigger_id)
        metrics on terminal / attention / timeout

Versions: ``saga_instance.version`` is also ``envelope.aggregateVersion`` of emitted events
(common-tables.sql). A transition that emits *n* events moves the version by *n* (at least 1), and
the events carry consecutive versions, so ``aggregateVersion`` stays strictly increasing per order
even when one transition emits two events (OrderShipped + InvoiceIssued). Commands carry the final
version.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from edacommon.db import UnitOfWork
from edacommon.envelope import Causation, OutgoingMessage
from edacommon.ids import Clock
from edacommon.logging import get_logger
from edacommon.metrics import EdaMetrics
from edacommon.outbox import OutboxWriter
from edacommon.saga.repository import TRIGGER_DEADLINE, SagaRepository, SagaRow

log = get_logger(__name__)
KIT_KEY = "_kit"  # engine bookkeeping inside saga data: startedAt, stateEnteredAt


@dataclass(frozen=True, slots=True)
class PendingMessage:
    """A message decided by a transition, before the engine assigns its aggregate version."""

    topic: str
    record_type: str
    key: str
    body: Mapping[str, Any]
    aggregate_type: str
    is_event: bool
    aggregate_id: str | None = None


@dataclass(frozen=True, slots=True)
class SagaStep:
    state: str
    data: dict[str, Any]
    deadline_at: datetime | None
    step_attempts: int
    messages: list[PendingMessage] = field(default_factory=list)
    ignored: bool = False
    terminal: bool = False
    outcome: str | None = None          # counted in eda.saga.outcomes when set
    decision_reached: bool = False      # records eda.saga.step.duration{step="DECISION"}

    @classmethod
    def ignore(cls, row: SagaRow) -> SagaStep:
        return cls(state=row.state, data=row.data, deadline_at=row.deadline_at,
                   step_attempts=row.step_attempts, ignored=True)


Decide = Callable[[SagaRow | None, datetime], SagaStep | None]


@dataclass(frozen=True, slots=True)
class HandleResult:
    applied: bool
    row: SagaRow | None
    from_state: str | None = None


class SagaEngine:
    def __init__(self, *, saga_type: str, outbox: OutboxWriter, metrics: EdaMetrics, clock: Clock) -> None:
        self.saga_type = saga_type
        self._outbox = outbox
        self._metrics = metrics
        self._clock = clock

    def handle(self, uow: UnitOfWork, *, saga_id: str, trigger_type: str, trigger_id: str | None,
               decide: Decide, correlation_id: str | None = None, causation: Causation | None = None,
               locked_row: SagaRow | None = None) -> HandleResult:
        """Load (locked), decide, persist. ``decide`` gets ``None`` when the saga does not exist yet
        and may return a first step to create it, or ``None`` to ignore the trigger."""
        repo = SagaRepository(uow.session)
        now = self._clock.now()
        row = locked_row or repo.load_for_update(saga_id)
        step = decide(row, now)
        if step is None or step.ignored:
            return HandleResult(False, row)
        from_state = row.state if row else "NEW"
        old_version = row.version if row else 0
        n_events = sum(1 for m in step.messages if m.is_event)
        new_version = old_version + max(1, n_events)
        data = dict(step.data)
        kit = dict(data.get(KIT_KEY) or {})
        kit.setdefault("startedAt", now.isoformat())
        if step.state != from_state:
            entered = kit.get("stateEnteredAt")
            if row is not None and entered:
                self._metrics.saga_step_duration(saga_type=self.saga_type, step=from_state,
                                                 seconds=(now - datetime.fromisoformat(entered)).total_seconds())
            kit["stateEnteredAt"] = now.isoformat()
        data[KIT_KEY] = kit
        corr = (row.correlation_id if row else None) or correlation_id or saga_id
        new_row = SagaRow(
            saga_id=saga_id, saga_type=self.saga_type, state=step.state, data=data, version=new_version,
            deadline_at=None if step.terminal else step.deadline_at, step_attempts=step.step_attempts,
            correlation_id=corr, completed_at=now if step.terminal else (row.completed_at if row else None),
        )
        # Outbox first or last makes no difference inside one transaction; do it first so a
        # serialisation error aborts before any saga write.
        next_event_version = old_version
        for m in step.messages:
            if m.is_event:
                next_event_version += 1
                version = next_event_version
            else:
                version = new_version
            self._outbox.append(uow.session, OutgoingMessage(
                topic=m.topic, record_type=m.record_type, key=m.key, body=m.body,
                aggregate_type=m.aggregate_type, aggregate_id=m.aggregate_id or saga_id,
                aggregate_version=version, causation=causation,
            ))
        if row is None:
            repo.insert(new_row, now)
        else:
            repo.save(new_row, expected_version=old_version, now=now)
        repo.append_transition(saga_id=saga_id, seq=new_version, from_state=from_state, to_state=step.state,
                               trigger_type=trigger_type, trigger_id=trigger_id, at=now)
        self._record_metrics(trigger_type, from_state, step, kit, now)
        log.info("saga transition", saga_type=self.saga_type, saga_id=saga_id, from_state=from_state,
                 to_state=step.state, trigger=trigger_type, version=new_version)
        return HandleResult(True, new_row, from_state)

    def _record_metrics(self, trigger_type: str, from_state: str, step: SagaStep, kit: dict[str, Any],
                        now: datetime) -> None:
        if trigger_type == TRIGGER_DEADLINE:
            self._metrics.saga_step_timeout(saga_type=self.saga_type, state=from_state)
        started = datetime.fromisoformat(kit["startedAt"])
        if step.decision_reached:
            self._metrics.saga_step_duration(saga_type=self.saga_type, step="DECISION",
                                             seconds=(now - started).total_seconds())
        if step.outcome:
            self._metrics.saga_outcome(saga_type=self.saga_type, outcome=step.outcome)
            if step.terminal:
                self._metrics.saga_duration(saga_type=self.saga_type, outcome=step.outcome,
                                            seconds=(now - started).total_seconds())
