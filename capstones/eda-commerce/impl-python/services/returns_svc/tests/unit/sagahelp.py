"""Helpers for pure returns-saga tests: run triggers, following pass-through states like the application."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from returns_svc.domain import saga as S
from returns_svc.domain.policy import ReturnLine

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
POLICY = S.Policy(auto_approve_limit_minor=50000, parcel_due=timedelta(days=14))


@dataclass
class Run:
    state: S.State
    data: S.SagaData
    attempts: int = 0
    deadline: datetime | None = None
    now: datetime = NOW
    commands: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    outcomes: list[str] = field(default_factory=list)
    path: list[str] = field(default_factory=list)
    _seq: itertools.count[int] = field(default_factory=itertools.count)

    def ids(self) -> S.Ids:
        return S.Ids(new_id=lambda: f"id-{next(self._seq)}", rma_number=lambda: "RMA-2026-000042")

    def apply(self, d: S.Decision) -> S.Decision:
        self.state, self.data, self.attempts, self.deadline = d.state, d.data, d.attempts, d.deadline
        self.commands += [c.name for c in d.commands]
        self.events += [e.name for e in d.events]
        if d.outcome:
            self.outcomes.append(d.outcome)
        self.path.append(d.state.value)
        return d

    def send(self, t: S.Trigger, *, advance: timedelta = timedelta(0)) -> S.Decision:
        self.now += advance
        d = S.transition(self.state, self.data, self.attempts, t, self.now, POLICY, self.ids(), deadline=self.deadline)
        if d.ignored:
            self.data = d.data
            return d
        self.apply(d)
        while d.needs_continue:
            d = self.apply(S.transition(self.state, self.data, self.attempts, S.Continue(), self.now, POLICY, self.ids()))
        return d


def data(qty: int = 2, unit: int = 12999, reason: str = "CHANGED_MIND", fee: int = 0) -> S.SagaData:
    return S.SagaData(
        return_id="ret-1",
        order_id="o-1",
        customer_id="c-1",
        currency="EUR",
        reason=reason,
        lines=(ReturnLine("l-1", "SKU-1001", qty, unit),),
        shipping_fee_minor=fee,
        pickup_from={"city": "Berlin"},
        warehouse_id="wh-1",
        payment_id="pay-1",
    )


def started(**kw: object) -> Run:
    r = Run(S.State.REQUESTED, data(**kw))  # type: ignore[arg-type]
    r.apply(S.start(r.data))
    d = S.transition(r.state, r.data, 0, S.Continue(), r.now, POLICY, r.ids())
    r.apply(d)
    while d.needs_continue:
        d = r.apply(S.transition(r.state, r.data, r.attempts, S.Continue(), r.now, POLICY, r.ids()))
    return r
