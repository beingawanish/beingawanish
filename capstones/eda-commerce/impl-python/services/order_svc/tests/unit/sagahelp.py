"""Helpers to drive the pure order saga in tests."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from order_svc.domain import saga as S

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
CFG = S.Timeouts()


def minter() -> S.Mint:
    c = itertools.count(1)
    return lambda: f"id-{next(c)}"


CHECKOUT = S.CheckoutSubmitted(
    order_id="o1", customer_id="c1", currency="EUR", total_minor=25998,
    lines=(S.Line("l1", "SKU-1001", "Trail Running Shoe", 2, 12999, 25998),),
    ship_to={"recipientName": "Jane Doe", "line1": "x", "city": "Berlin", "postalCode": "10115", "countryCode": "DE"},
    shipping_method="STANDARD", payment_token="tok_visa_ok")


@dataclass
class Run:
    """A saga instance driven through triggers, recording everything it decided."""

    state: S.State
    data: S.SagaData
    attempts: int = 0
    deadline: datetime | None = None
    now: datetime = NOW
    mint: S.Mint = field(default_factory=minter)
    commands: list[S.Command] = field(default_factory=list)
    events: list[S.Event] = field(default_factory=list)
    outcomes: list[str] = field(default_factory=list)
    last: S.Decision | None = None

    @classmethod
    def started(cls) -> Run:
        mint = minter()
        d = S.start(CHECKOUT, NOW, CFG, mint)
        r = cls(d.state, d.data, d.attempts, d.deadline, mint=mint)
        r.commands += d.commands
        r.events += d.events
        r.last = d
        return r

    def send(self, t: S.Trigger, *, after: timedelta = timedelta(seconds=1)) -> S.Decision:
        self.now += after
        d = S.transition(self.state, self.data, self.attempts, t, self.now, CFG, self.mint, self.deadline)
        self.last = d
        if not d.ignored:
            self.state, self.data, self.attempts, self.deadline = d.state, d.data, d.attempts, d.deadline
            self.commands += d.commands
            self.events += d.events
            if d.outcome:
                self.outcomes.append(d.outcome)
        return d

    def deadline_fires(self) -> S.Decision:
        assert self.deadline is not None, f"no deadline in {self.state}"
        return self.send(S.Deadline(), after=(self.deadline - self.now) + timedelta(milliseconds=1))

    def cmd_names(self) -> list[str]:
        return [c.name for c in self.commands]

    def evt_names(self) -> list[str]:
        return [e.name for e in self.events]

    # replies matched to the ids the saga minted
    def stock_reserved(self) -> S.Decision:
        return self.send(S.StockReserved(self.data.reservation_id))

    def authorized(self) -> S.Decision:
        assert self.data.payment_id
        return self.send(S.PaymentAuthorized(self.data.payment_id, "2026-11-25T10:00:00+00:00"))

    def committed(self) -> S.Decision:
        return self.send(S.ReservationCommitted(self.data.reservation_id))

    def accepted(self) -> S.Decision:
        assert self.data.fulfilment_id
        return self.send(S.FulfilmentAccepted(self.data.fulfilment_id))

    def packed(self) -> S.Decision:
        assert self.data.fulfilment_id
        return self.send(S.OrderPacked(self.data.fulfilment_id))

    def dispatched(self) -> S.Decision:
        assert self.data.fulfilment_id
        return self.send(S.OrderDispatched(self.data.fulfilment_id, "ship-1"))

    def captured(self) -> S.Decision:
        assert self.data.payment_id
        return self.send(S.PaymentCaptured(self.data.payment_id, 25998))

    def delivered(self) -> S.Decision:
        return self.send(S.ShipmentDelivered("ship-1", "2026-11-20T14:05:00+00:00"))

    def to(self, target: S.State) -> Run:
        steps = [self.stock_reserved, self.authorized, self.committed, self.accepted, self.packed, self.dispatched,
                 self.captured, self.delivered]
        for step in steps:
            if self.state is target:
                return self
            step()
        assert self.state is target, self.state
        return self
