"""The order saga as a pure transition function (architecture §5, ADR-0008, ADR-0015).

``transition(state, data, attempts, trigger, now, timeouts, mint) -> Decision``

* No I/O, no clock, no random: ``now`` is passed in and ``mint`` produces new business ids.
* Every row of the state table in architecture §5.1/§5.2 is a branch below, and has a unit test.
* Rules of §5.3 are enforced here:

  1. one transition per call (the saga kit wraps it in one transaction);
  2. business ids (reservationId, paymentId, fulfilmentId, invoiceId) are minted once, when the saga
     enters the step, stored in ``data`` and reused for every resend;
  3. replies are matched by business id and state, never by arrival order: a reply for another id,
     or for a step we already left, is *ignored* (or triggers a compensation, see below);
  4. early events (a ``ShipmentDelivered`` before ``PaymentCaptured``...) are stored in
     ``data.early`` and applied when the saga reaches the state that expects them;
  5. the pivot is ``OrderDispatched``: before it every failure compensates; after it nothing is
     compensated, failures retry or go to NEEDS_ATTENTION;
  6. compensations are commands with business ids; CANCELLING waits for every reply.

A late ``PaymentAuthorized`` (or ``StockReserved``) for a saga that is already cancelling or
cancelled is not an error: the saga records it and sends the matching compensation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, ClassVar

SAGA_TYPE = "ORDER"
RETURN_WINDOW = timedelta(days=30)
SHIPPED_TIMEOUT = timedelta(days=30)
STOCK_MAX_RESENDS = 2
PAYMENT_MAX_RESENDS = 1
COMPENSATION_ALERT_AFTER = 10
CAPTURE_BACKOFF = timedelta(minutes=1)
CAPTURE_BACKOFF_MAX = timedelta(hours=1)


class State(StrEnum):
    RESERVING_STOCK = "RESERVING_STOCK"
    AUTHORIZING_PAYMENT = "AUTHORIZING_PAYMENT"
    COMMITTING_STOCK = "COMMITTING_STOCK"
    AWAITING_FULFILMENT_ACK = "AWAITING_FULFILMENT_ACK"
    FULFILLING = "FULFILLING"
    PACKED = "PACKED"
    CAPTURING = "CAPTURING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


TERMINAL = frozenset({State.DELIVERED, State.CANCELLED})
PRE_DECISION = frozenset({State.RESERVING_STOCK, State.AUTHORIZING_PAYMENT, State.COMMITTING_STOCK})
PAST_PIVOT = frozenset({State.CAPTURING, State.SHIPPED, State.DELIVERED})


class Compensation(StrEnum):
    RELEASE_RESERVATION = "RELEASE_RESERVATION"
    VOID_PAYMENT = "VOID_PAYMENT"
    CANCEL_FULFILMENT = "CANCEL_FULFILMENT"


class CancelReason(StrEnum):
    OUT_OF_STOCK = "OUT_OF_STOCK"
    PAYMENT_DECLINED = "PAYMENT_DECLINED"
    RESERVATION_EXPIRED = "RESERVATION_EXPIRED"
    FULFILMENT_FAILED = "FULFILMENT_FAILED"
    CUSTOMER_REQUESTED = "CUSTOMER_REQUESTED"
    SAGA_TIMEOUT = "SAGA_TIMEOUT"


@dataclass(frozen=True, slots=True)
class Timeouts:
    stock: timedelta = timedelta(seconds=30)
    payment: timedelta = timedelta(seconds=180)
    commit: timedelta = timedelta(seconds=30)
    fulfilment_ack: timedelta = timedelta(seconds=600)
    fulfilment_max_resends: int = 3
    dispatch: timedelta = timedelta(hours=24)
    capture: timedelta = timedelta(seconds=300)
    compensation: timedelta = timedelta(seconds=60)


# ----------------------------------------------------------------------------------------- data
@dataclass(frozen=True, slots=True)
class Line:
    line_id: str
    sku: str
    product_name: str
    quantity: int
    unit_price_minor: int
    line_total_minor: int


@dataclass(frozen=True, slots=True)
class SagaData:
    """Saga-local data, stored as JSON in ``saga_instance.data``."""

    order_id: str
    customer_id: str
    currency: str
    total_minor: int
    lines: tuple[Line, ...]
    ship_to: dict[str, Any]
    shipping_method: str
    payment_token: str
    reservation_id: str
    payment_id: str | None = None
    fulfilment_id: str | None = None
    invoice_id: str | None = None
    shipment_id: str | None = None
    carrier: str | None = None
    tracking_number: str | None = None
    reservation_held: bool = False
    reservation_committed: bool = False
    reservation_expired: bool = False
    reservation_released: bool = False
    payment_requested: bool = False
    payment_authorized: bool = False
    payment_voided: bool = False
    payment_captured: bool = False
    authorization_expires_at: str | None = None
    fulfilment_requested: bool = False
    fulfilment_attempt: int = 0
    fulfilment_failed: bool = False
    fulfilment_cancelled: bool = False
    capture_attempt: int = 0
    cancel_reason: str | None = None
    cancel_detail: str | None = None
    pending: tuple[str, ...] = ()            # outstanding compensations (Compensation values)
    early: tuple[dict[str, Any], ...] = ()   # triggers that arrived before their state
    resume_state: str | None = None          # where an operator retry goes from NEEDS_ATTENTION
    attention_issue: str | None = None
    decided: bool = False                    # reached confirmed-or-cancelled (DECISION metric)
    order_shipped_emitted: bool = False
    invoice_issued: bool = False
    compensation_alerted: bool = False
    notes: tuple[str, ...] = ()              # late/irrelevant replies recorded for the ops view

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["lines"] = [asdict(x) for x in self.lines]
        d["pending"] = list(self.pending)
        d["early"] = list(self.early)
        d["notes"] = list(self.notes)
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> SagaData:
        known = {f for f in cls.__dataclass_fields__}  # tolerate bookkeeping keys (e.g. the kit's)
        v = {k: x for k, x in d.items() if k in known}
        v["lines"] = tuple(Line(**x) for x in v.get("lines", ()))
        v["pending"] = tuple(v.get("pending", ()))
        v["early"] = tuple(v.get("early", ()))
        v["notes"] = tuple(v.get("notes", ()))
        return cls(**v)

    def note(self, text: str) -> SagaData:
        return replace(self, notes=(*self.notes[-19:], text))


# ------------------------------------------------------------------------------------- triggers
@dataclass(frozen=True, slots=True)
class Trigger:
    kind: ClassVar[str] = "TRIGGER"


@dataclass(frozen=True, slots=True)
class CheckoutSubmitted(Trigger):
    kind: ClassVar[str] = "CheckoutSubmitted"
    order_id: str
    customer_id: str
    currency: str
    total_minor: int
    lines: tuple[Line, ...]
    ship_to: dict[str, Any]
    shipping_method: str
    payment_token: str


@dataclass(frozen=True, slots=True)
class StockReserved(Trigger):
    kind: ClassVar[str] = "StockReserved"
    reservation_id: str


@dataclass(frozen=True, slots=True)
class StockReservationRejected(Trigger):
    kind: ClassVar[str] = "StockReservationRejected"
    reservation_id: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ReservationCommitted(Trigger):
    kind: ClassVar[str] = "ReservationCommitted"
    reservation_id: str


@dataclass(frozen=True, slots=True)
class ReservationReleased(Trigger):
    kind: ClassVar[str] = "ReservationReleased"
    reservation_id: str


@dataclass(frozen=True, slots=True)
class ReservationExpired(Trigger):
    kind: ClassVar[str] = "ReservationExpired"
    reservation_id: str


@dataclass(frozen=True, slots=True)
class PaymentAuthorized(Trigger):
    kind: ClassVar[str] = "PaymentAuthorized"
    payment_id: str
    authorization_expires_at: str | None = None


@dataclass(frozen=True, slots=True)
class PaymentDeclined(Trigger):
    kind: ClassVar[str] = "PaymentDeclined"
    payment_id: str
    reason: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PaymentCaptured(Trigger):
    kind: ClassVar[str] = "PaymentCaptured"
    payment_id: str
    amount_minor: int = 0


@dataclass(frozen=True, slots=True)
class PaymentCaptureFailed(Trigger):
    kind: ClassVar[str] = "PaymentCaptureFailed"
    payment_id: str
    reason: str = "UNKNOWN"
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class PaymentVoided(Trigger):
    kind: ClassVar[str] = "PaymentVoided"
    payment_id: str


@dataclass(frozen=True, slots=True)
class FulfilmentAccepted(Trigger):
    kind: ClassVar[str] = "FulfilmentAccepted"
    fulfilment_id: str


@dataclass(frozen=True, slots=True)
class OrderPacked(Trigger):
    kind: ClassVar[str] = "OrderPacked"
    fulfilment_id: str


@dataclass(frozen=True, slots=True)
class OrderDispatched(Trigger):
    kind: ClassVar[str] = "OrderDispatched"
    fulfilment_id: str
    shipment_id: str


@dataclass(frozen=True, slots=True)
class FulfilmentFailed(Trigger):
    kind: ClassVar[str] = "FulfilmentFailed"
    fulfilment_id: str
    reason: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class FulfilmentCancelled(Trigger):
    kind: ClassVar[str] = "FulfilmentCancelled"
    fulfilment_id: str


@dataclass(frozen=True, slots=True)
class ShipmentCreated(Trigger):
    kind: ClassVar[str] = "ShipmentCreated"
    shipment_id: str
    carrier: str
    tracking_number: str
    outbound: bool = True


@dataclass(frozen=True, slots=True)
class ShipmentDelivered(Trigger):
    kind: ClassVar[str] = "ShipmentDelivered"
    shipment_id: str
    delivered_at: str
    outbound: bool = True


@dataclass(frozen=True, slots=True)
class ShipmentException(Trigger):
    kind: ClassVar[str] = "ShipmentException"
    shipment_id: str
    code: str
    outbound: bool = True


@dataclass(frozen=True, slots=True)
class Deadline(Trigger):
    kind: ClassVar[str] = "DEADLINE"


@dataclass(frozen=True, slots=True)
class OperatorRetry(Trigger):
    kind: ClassVar[str] = "OPERATOR"


_DEFERRABLE: dict[str, type[Trigger]] = {
    t.kind: t for t in (OrderPacked, OrderDispatched, ShipmentDelivered, ShipmentException)
}


def _store(t: Trigger) -> dict[str, Any]:
    return {"kind": t.kind, **asdict(t)}


def _load(d: dict[str, Any]) -> Trigger:
    cls = _DEFERRABLE[d["kind"]]
    return cls(**{k: v for k, v in d.items() if k != "kind"})


# ------------------------------------------------------------------------------------- decisions
@dataclass(frozen=True, slots=True)
class Command:
    name: str                  # ReserveStock, AuthorizePayment, ...
    business_id: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Event:
    name: str                  # OrderPlaced, OrderConfirmed, ...
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Decision:
    state: State
    data: SagaData
    attempts: int
    deadline: datetime | None
    commands: tuple[Command, ...] = ()
    events: tuple[Event, ...] = ()        # in emission order; IssueInvoice is an event placeholder
    ignored: bool = False
    outcome: str | None = None            # DELIVERED | CANCELLED | MANUAL_REVIEW
    decision_reached: bool = False

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL


Mint = Callable[[], str]


# ---------------------------------------------------------------------------------- the machine
def start(t: CheckoutSubmitted, now: datetime, cfg: Timeouts, mint: Mint) -> Decision:
    """CheckoutSubmitted / emit OrderPlaced, send ReserveStock."""
    data = SagaData(order_id=t.order_id, customer_id=t.customer_id, currency=t.currency, total_minor=t.total_minor,
                    lines=t.lines, ship_to=t.ship_to, shipping_method=t.shipping_method, payment_token=t.payment_token,
                    reservation_id=mint())
    return Decision(State.RESERVING_STOCK, data, 0, now + cfg.stock,
                    commands=(_reserve(data),), events=(Event("OrderPlaced"),))


def transition(state: State, data: SagaData, attempts: int, t: Trigger, now: datetime, cfg: Timeouts,
               mint: Mint, deadline: datetime | None = None) -> Decision:
    """``deadline`` is the stored deadline; decisions that only record a fact keep it."""
    d = _step(state, data, attempts, t, now, cfg, mint, deadline)
    # Rule 4: after any real move, apply early events that the new state expects.
    while not d.ignored and d.data.early and d.state != state:
        state = d.state
        d = _drain(d, now, cfg, mint)
    return d


def _drain(d: Decision, now: datetime, cfg: Timeouts, mint: Mint) -> Decision:
    for i, raw in enumerate(d.data.early):
        trig = _load(raw)
        rest = d.data.early[:i] + d.data.early[i + 1:]
        candidate = _step(d.state, replace(d.data, early=rest), d.attempts, trig, now, cfg, mint, d.deadline)
        if not candidate.ignored and candidate.data.early != (*rest, raw):
            return _merge(d, candidate)
    return d


def _merge(first: Decision, second: Decision) -> Decision:
    return replace(second, commands=first.commands + second.commands, events=first.events + second.events,
                   outcome=second.outcome or first.outcome,
                   decision_reached=first.decision_reached or second.decision_reached)


def _ignore(state: State, data: SagaData, attempts: int, deadline: datetime | None = None,
            why: str | None = None) -> Decision:
    return Decision(state, data, attempts, deadline, ignored=True)


def _defer(state: State, data: SagaData, attempts: int, t: Trigger, deadline: datetime | None) -> Decision:
    if _store(t) in data.early:
        return _ignore(state, data, attempts)
    return Decision(state, replace(data, early=(*data.early, _store(t))), attempts, deadline)


def _step(s: State, d: SagaData, attempts: int, t: Trigger, now: datetime, cfg: Timeouts, mint: Mint,
          keep: datetime | None) -> Decision:
    # ---- terminal states: only safety-net compensations ---------------------------------------
    if s in TERMINAL:
        return _after_terminal(s, d, attempts, t)

    # ---- facts recorded whatever the state ------------------------------------------------
    if isinstance(t, ShipmentCreated):
        if not t.outbound or d.tracking_number == t.tracking_number:
            return _ignore(s, d, attempts)
        d2 = replace(d, shipment_id=d.shipment_id or t.shipment_id, carrier=t.carrier, tracking_number=t.tracking_number)
        if s is State.SHIPPED and d.payment_captured and not d.order_shipped_emitted:
            return Decision(s, replace(d2, order_shipped_emitted=True), attempts, keep, events=(Event("OrderShipped"),))
        return Decision(s, d2, attempts, keep)
    if isinstance(t, CheckoutSubmitted):
        return _ignore(s, d, attempts)  # duplicate start (new eventId, same orderId)

    if s is State.CANCELLING:
        return _cancelling(d, attempts, t, now, cfg, keep)

    if s is State.NEEDS_ATTENTION:
        return _attention(d, attempts, t, now, cfg, mint)

    # ---- RESERVING_STOCK ---------------------------------------------------------------------
    if s is State.RESERVING_STOCK:
        if isinstance(t, StockReserved) and t.reservation_id == d.reservation_id:
            d2 = replace(d, reservation_held=True, payment_id=d.payment_id or mint(), payment_requested=True)
            return Decision(State.AUTHORIZING_PAYMENT, d2, 0, now + cfg.payment, commands=(_authorize(d2),))
        if isinstance(t, StockReservationRejected) and t.reservation_id == d.reservation_id:
            d2 = replace(d, cancel_reason=CancelReason.OUT_OF_STOCK, cancel_detail=t.detail or None, decided=True)
            return Decision(State.CANCELLED, d2, 0, None, events=(Event("OrderCancelled"),), outcome="CANCELLED",
                            decision_reached=True)
        if isinstance(t, Deadline):
            if attempts < STOCK_MAX_RESENDS:
                return Decision(s, d, attempts + 1, now + cfg.stock, commands=(_reserve(d),))
            # "cancel and send ReleaseReservation in case the reply was lost"
            return _begin_cancel(replace(d, reservation_held=True), CancelReason.SAGA_TIMEOUT,
                                 "no stock reply after 2 resends", now, cfg)
        return _late_or_ignored(s, d, attempts, t, keep, now, cfg)

    # ---- AUTHORIZING_PAYMENT -----------------------------------------------------------------
    if s is State.AUTHORIZING_PAYMENT:
        if isinstance(t, PaymentAuthorized) and t.payment_id == d.payment_id:
            d2 = replace(d, payment_authorized=True, authorization_expires_at=t.authorization_expires_at)
            if d.reservation_expired:
                # §5.7: the reservation is already gone -> cancel and void.
                return _begin_cancel(d2, CancelReason.RESERVATION_EXPIRED, "reservation expired during payment", now, cfg)
            return Decision(State.COMMITTING_STOCK, d2, 0, now + cfg.commit, commands=(_commit(d2),))
        if isinstance(t, PaymentDeclined) and t.payment_id == d.payment_id:
            d2 = replace(d, payment_requested=False)  # nothing held at the PSP: no void needed
            return _begin_cancel(d2, CancelReason.PAYMENT_DECLINED, t.reason, now, cfg)
        if isinstance(t, ReservationExpired) and t.reservation_id == d.reservation_id:
            # Record it; the state is still AUTHORIZING_PAYMENT (§5.7).
            return Decision(s, replace(d, reservation_expired=True, reservation_held=False), attempts, keep)
        if isinstance(t, Deadline):
            if attempts < PAYMENT_MAX_RESENDS:
                return Decision(s, d, attempts + 1, now + cfg.payment, commands=(_authorize(d),))
            return _begin_cancel(d, CancelReason.SAGA_TIMEOUT, "no payment decision after 1 resend", now, cfg)
        return _late_or_ignored(s, d, attempts, t, keep, now, cfg)

    # ---- COMMITTING_STOCK --------------------------------------------------------------------
    if s is State.COMMITTING_STOCK:
        if isinstance(t, ReservationCommitted) and t.reservation_id == d.reservation_id:
            d2 = replace(d, reservation_held=False, reservation_committed=True, fulfilment_id=d.fulfilment_id or mint(),
                         fulfilment_requested=True,
                         fulfilment_attempt=1, decided=True)
            return Decision(State.AWAITING_FULFILMENT_ACK, d2, 0, now + cfg.fulfilment_ack,
                            commands=(_request_fulfilment(d2),), events=(Event("OrderConfirmed"),),
                            decision_reached=not d.decided)
        if isinstance(t, ReservationExpired) and t.reservation_id == d.reservation_id:
            d2 = replace(d, reservation_expired=True, reservation_held=False)
            return _begin_cancel(d2, CancelReason.RESERVATION_EXPIRED, "reservation expired before commit", now, cfg)
        if isinstance(t, Deadline):
            return Decision(s, d, attempts + 1, now + cfg.commit, commands=(_commit(d),))
        return _late_or_ignored(s, d, attempts, t, keep, now, cfg)

    # ---- AWAITING_FULFILMENT_ACK -------------------------------------------------------------
    if s is State.AWAITING_FULFILMENT_ACK:
        if isinstance(t, FulfilmentAccepted) and t.fulfilment_id == d.fulfilment_id:
            return Decision(State.FULFILLING, d, 0, now + cfg.dispatch)
        if isinstance(t, OrderPacked) and t.fulfilment_id == d.fulfilment_id:
            # Accepted was lost or reordered (retry topic): packed implies accepted.
            return Decision(State.FULFILLING, replace(d, early=(*d.early, _store(t))), 0, now + cfg.dispatch)
        if isinstance(t, OrderDispatched) and t.fulfilment_id == d.fulfilment_id:
            return _defer(s, d, attempts, t, keep)
        if isinstance(t, FulfilmentFailed) and t.fulfilment_id == d.fulfilment_id:
            return _begin_cancel(replace(d, fulfilment_failed=True), CancelReason.FULFILMENT_FAILED, t.reason, now, cfg)
        if isinstance(t, Deadline):
            if d.fulfilment_attempt <= cfg.fulfilment_max_resends:
                d2 = replace(d, fulfilment_attempt=d.fulfilment_attempt + 1)
                return Decision(s, d2, attempts + 1, now + cfg.fulfilment_ack, commands=(_request_fulfilment(d2),))
            return _attention_now(d, s, "warehouse did not accept the fulfilment request", State.AWAITING_FULFILMENT_ACK)
        return _late_or_ignored(s, d, attempts, t, keep, now, cfg)

    # ---- FULFILLING / PACKED -----------------------------------------------------------------
    if s in (State.FULFILLING, State.PACKED):
        if isinstance(t, OrderPacked) and t.fulfilment_id == d.fulfilment_id:
            if s is State.PACKED:
                return _ignore(s, d, attempts)
            return Decision(State.PACKED, d, 0, now + cfg.dispatch)
        if isinstance(t, OrderDispatched) and t.fulfilment_id == d.fulfilment_id:
            if s is State.FULFILLING:
                return _defer(s, d, attempts, t, keep)
            return _pivot(d, t, now, cfg, mint)
        if isinstance(t, FulfilmentFailed) and t.fulfilment_id == d.fulfilment_id:
            return _begin_cancel(replace(d, fulfilment_failed=True), CancelReason.FULFILMENT_FAILED, t.reason, now, cfg)
        if isinstance(t, FulfilmentAccepted):
            return _ignore(s, d, attempts)  # duplicate ack after a resend
        if isinstance(t, Deadline):
            return _attention_now(d, s, f"no dispatch within the deadline in {s.value}", State.AWAITING_FULFILMENT_ACK)
        return _late_or_ignored(s, d, attempts, t, keep, now, cfg)

    # ---- CAPTURING (past the pivot: retry, never compensate) ---------------------------------
    if s is State.CAPTURING:
        if isinstance(t, PaymentCaptured) and t.payment_id == d.payment_id:
            return _shipped(d, now)
        if isinstance(t, PaymentCaptureFailed) and t.payment_id == d.payment_id:
            if t.retryable:
                backoff = min(CAPTURE_BACKOFF * (2 ** max(d.capture_attempt - 1, 0)), CAPTURE_BACKOFF_MAX)
                return Decision(s, d.note(f"capture failed ({t.reason}), retry in {backoff}"), attempts, now + backoff)
            return _attention_now(d, s, f"capture failed after dispatch: {t.reason}", State.CAPTURING)
        if isinstance(t, Deadline):
            d2 = replace(d, capture_attempt=d.capture_attempt + 1)
            return Decision(s, d2, attempts + 1, now + cfg.capture, commands=(_capture(d2),))
        if isinstance(t, (ShipmentDelivered, ShipmentException)) and t.outbound:
            return _defer(s, d, attempts, t, keep)
        return _late_or_ignored(s, d, attempts, t, keep, now, cfg)

    # ---- SHIPPED -----------------------------------------------------------------------------
    if s is State.SHIPPED:
        if isinstance(t, ShipmentDelivered) and t.outbound:
            return _delivered(d, t)
        if isinstance(t, ShipmentException) and t.outbound:
            if t.code == "LOST":
                return _attention_now(d, s, "carrier reports the parcel lost", None)
            return Decision(s, d.note(f"shipment exception {t.code}"), attempts, keep)
        if isinstance(t, Deadline):
            return _attention_now(d, s, "no delivery within 30 days", None)
        return _late_or_ignored(s, d, attempts, t, keep, now, cfg)

    return _ignore(s, d, attempts)


# ---------------------------------------------------------------------------------- helpers
def _late_or_ignored(s: State, d: SagaData, attempts: int, t: Trigger, keep: datetime | None,
                     now: datetime, cfg: Timeouts) -> Decision:
    """Pre-pivot early arrivals of shipping events are stored; everything else is late or foreign."""
    if isinstance(t, (ShipmentDelivered, ShipmentException)) and t.outbound and s not in PAST_PIVOT:
        return _defer(s, d, attempts, t, keep)
    if isinstance(t, ReservationExpired) and t.reservation_id == d.reservation_id and d.reservation_held:
        return Decision(s, replace(d, reservation_expired=True, reservation_held=False), attempts, keep)
    return _ignore(s, d, attempts)


def _begin_cancel(d: SagaData, reason: CancelReason, detail: str | None, now: datetime, cfg: Timeouts) -> Decision:
    pending: list[str] = []
    commands: list[Command] = []
    if (d.reservation_held or d.reservation_committed) and not d.reservation_expired:
        pending.append(Compensation.RELEASE_RESERVATION)
        commands.append(Command("ReleaseReservation", d.reservation_id, {"reason": reason.value}))
    if d.payment_id and (d.payment_authorized or d.payment_requested) and not d.payment_voided:
        pending.append(Compensation.VOID_PAYMENT)
        commands.append(Command("VoidPayment", d.payment_id, {"reason": reason.value}))
    if d.fulfilment_requested and d.fulfilment_id and not (d.fulfilment_failed or d.fulfilment_cancelled):
        pending.append(Compensation.CANCEL_FULFILMENT)
        commands.append(Command("CancelFulfilment", d.fulfilment_id, {"reason": reason.value}))
    first_decision = not d.decided
    d2 = replace(d, cancel_reason=reason.value, cancel_detail=detail, pending=tuple(pending), decided=True)
    if not pending:
        return Decision(State.CANCELLED, d2, 0, None, events=(Event("OrderCancelled"),), outcome="CANCELLED",
                        decision_reached=first_decision)
    return Decision(State.CANCELLING, d2, 0, now + cfg.compensation, commands=tuple(commands),
                    decision_reached=first_decision)


def _cancelling(d: SagaData, attempts: int, t: Trigger, now: datetime, cfg: Timeouts,
                keep: datetime | None) -> Decision:
    pending = list(d.pending)
    d2 = d
    extra: list[Command] = []
    if isinstance(t, ReservationReleased) and t.reservation_id == d.reservation_id:
        d2 = replace(d, reservation_held=False, reservation_committed=False, reservation_released=True)
        _discard(pending, Compensation.RELEASE_RESERVATION)
    elif isinstance(t, ReservationExpired) and t.reservation_id == d.reservation_id:
        d2 = replace(d, reservation_held=False, reservation_expired=True)
        _discard(pending, Compensation.RELEASE_RESERVATION)
    elif isinstance(t, PaymentVoided) and t.payment_id == d.payment_id:
        d2 = replace(d, payment_voided=True)
        _discard(pending, Compensation.VOID_PAYMENT)
    elif isinstance(t, PaymentDeclined) and t.payment_id == d.payment_id:
        d2 = replace(d, payment_requested=False, payment_authorized=False)  # nothing held at the PSP
        _discard(pending, Compensation.VOID_PAYMENT)
    elif isinstance(t, FulfilmentCancelled) and t.fulfilment_id == d.fulfilment_id:
        d2 = replace(d, fulfilment_cancelled=True)
        _discard(pending, Compensation.CANCEL_FULFILMENT)
    elif isinstance(t, FulfilmentFailed) and t.fulfilment_id == d.fulfilment_id:
        d2 = replace(d, fulfilment_failed=True)
        _discard(pending, Compensation.CANCEL_FULFILMENT)
    elif isinstance(t, PaymentAuthorized) and t.payment_id == d.payment_id and not d.payment_voided:
        # Rule 3: a late authorisation while cancelling is recorded and voided, not an error.
        d2 = replace(d, payment_authorized=True)
        if Compensation.VOID_PAYMENT not in pending:
            pending.append(Compensation.VOID_PAYMENT)
            extra.append(Command("VoidPayment", d.payment_id, {"reason": d.cancel_reason or "CANCELLED"}))
        else:
            return _ignore(State.CANCELLING, d2, attempts)
    elif isinstance(t, StockReserved) and t.reservation_id == d.reservation_id and not (
            d.reservation_expired or d.reservation_released):
        # A stale duplicate after expiry/release is ignored: inventory never re-holds that id.
        d2 = replace(d, reservation_held=True)
        if Compensation.RELEASE_RESERVATION not in pending:
            pending.append(Compensation.RELEASE_RESERVATION)
            extra.append(Command("ReleaseReservation", d.reservation_id, {"reason": d.cancel_reason or "CANCELLED"}))
        else:
            return _ignore(State.CANCELLING, d2, attempts)
    elif isinstance(t, Deadline):
        # Compensations must succeed: resend outstanding ones forever, with backoff; alert after 10.
        cmds = tuple(_compensation_command(d, Compensation(c)) for c in pending)
        n = attempts + 1
        backoff = cfg.compensation * min(2 ** min(n, 4), 16)
        events: tuple[Event, ...] = ()
        if n >= COMPENSATION_ALERT_AFTER and not d.compensation_alerted:
            events = (Event("OrderRequiresAttention", {"issue": f"compensations unconfirmed after {n} attempts: "
                                                                f"{', '.join(pending)}", "state": State.CANCELLING.value}),)
            d = replace(d, compensation_alerted=True)
        return Decision(State.CANCELLING, d, n, now + backoff, commands=cmds, events=events)
    else:
        return _ignore(State.CANCELLING, d, attempts)
    d3 = replace(d2, pending=tuple(pending))
    if not pending:
        return Decision(State.CANCELLED, d3, 0, None, commands=tuple(extra), events=(Event("OrderCancelled"),),
                        outcome="CANCELLED")
    return Decision(State.CANCELLING, d3, attempts, now + cfg.compensation if extra else keep, commands=tuple(extra))


def _discard(pending: list[str], c: Compensation) -> None:
    if c in pending:
        pending.remove(c)


def _compensation_command(d: SagaData, c: Compensation) -> Command:
    reason = d.cancel_reason or "CANCELLED"
    if c is Compensation.RELEASE_RESERVATION:
        return Command("ReleaseReservation", d.reservation_id, {"reason": reason})
    if c is Compensation.VOID_PAYMENT:
        assert d.payment_id
        return Command("VoidPayment", d.payment_id, {"reason": reason})
    assert d.fulfilment_id
    return Command("CancelFulfilment", d.fulfilment_id, {"reason": reason})


def _after_terminal(s: State, d: SagaData, attempts: int, t: Trigger) -> Decision:
    """Terminal states ignore everything, except that something still held gets compensated."""
    if s is State.CANCELLED:
        if isinstance(t, PaymentAuthorized) and t.payment_id == d.payment_id and not d.payment_voided:
            return Decision(s, replace(d, payment_authorized=True).note("late PaymentAuthorized after cancel: voided"),
                            attempts, None, commands=(Command("VoidPayment", t.payment_id, {"reason": "LATE_AUTHORIZATION"}),))
        if (isinstance(t, StockReserved) and t.reservation_id == d.reservation_id and not d.reservation_held
                and not (d.reservation_expired or d.reservation_released)):
            return Decision(s, replace(d, reservation_held=True).note("late StockReserved after cancel: released"),
                            attempts, None,
                            commands=(Command("ReleaseReservation", t.reservation_id, {"reason": "LATE_RESERVATION"}),))
        if isinstance(t, PaymentVoided) and t.payment_id == d.payment_id and not d.payment_voided:
            return Decision(s, replace(d, payment_voided=True), attempts, None)
        if isinstance(t, ReservationReleased) and t.reservation_id == d.reservation_id and d.reservation_held:
            return Decision(s, replace(d, reservation_held=False, reservation_released=True), attempts, None)
    return _ignore(s, d, attempts)


def _attention_now(d: SagaData, s: State, issue: str, resume: State | None) -> Decision:
    d2 = replace(d, attention_issue=issue, resume_state=resume.value if resume else None)
    return Decision(State.NEEDS_ATTENTION, d2, 0, None,
                    events=(Event("OrderRequiresAttention", {"issue": issue, "state": s.value}),),
                    outcome="MANUAL_REVIEW")


def _attention(d: SagaData, attempts: int, t: Trigger, now: datetime, cfg: Timeouts, mint: Mint) -> Decision:
    s = State.NEEDS_ATTENTION
    resume = State(d.resume_state) if d.resume_state else None
    if isinstance(t, OperatorRetry):
        if resume is State.AWAITING_FULFILMENT_ACK:
            d2 = replace(d, fulfilment_attempt=d.fulfilment_attempt + 1, attention_issue=None)
            return Decision(resume, d2, 0, now + cfg.fulfilment_ack, commands=(_request_fulfilment(d2),))
        if resume is State.CAPTURING:
            d2 = replace(d, capture_attempt=d.capture_attempt + 1, attention_issue=None)
            return Decision(resume, d2, 0, now + cfg.capture, commands=(_capture(d2),))
        return _ignore(s, d, attempts)
    # The world moved on while a human was looking: follow the facts (replies matched by id).
    if isinstance(t, FulfilmentAccepted) and t.fulfilment_id == d.fulfilment_id and resume is State.AWAITING_FULFILMENT_ACK:
        return Decision(State.FULFILLING, replace(d, attention_issue=None), 0, now + cfg.dispatch)
    if isinstance(t, OrderPacked) and t.fulfilment_id == d.fulfilment_id and resume is State.AWAITING_FULFILMENT_ACK:
        return Decision(State.PACKED, replace(d, attention_issue=None), 0, now + cfg.dispatch)
    if isinstance(t, OrderDispatched) and t.fulfilment_id == d.fulfilment_id and resume is State.AWAITING_FULFILMENT_ACK:
        return _pivot(replace(d, attention_issue=None), t, now, cfg, mint)
    if isinstance(t, PaymentCaptured) and t.payment_id == d.payment_id and resume is State.CAPTURING:
        return _shipped(replace(d, attention_issue=None), now)
    if isinstance(t, ShipmentDelivered) and t.outbound and d.payment_captured:
        return _delivered(replace(d, attention_issue=None), t)
    return _ignore(s, d, attempts)


def _pivot(d: SagaData, t: OrderDispatched, now: datetime, cfg: Timeouts, mint: Mint) -> Decision:
    """PACKED -> CAPTURING on OrderDispatched: from here on nothing is compensated (ADR-0015)."""
    d2 = replace(d, shipment_id=t.shipment_id, invoice_id=d.invoice_id or mint(), capture_attempt=1)
    return Decision(State.CAPTURING, d2, 0, now + cfg.capture, commands=(_capture(d2),))


def _shipped(d: SagaData, now: datetime) -> Decision:
    d2 = replace(d, payment_captured=True, invoice_issued=True)
    events: list[Event] = []
    if d2.tracking_number:
        events.append(Event("OrderShipped"))
        d2 = replace(d2, order_shipped_emitted=True)
    events.append(Event("InvoiceIssued"))  # the application renders the PDF, stores it, then emits
    return Decision(State.SHIPPED, d2, 0, now + SHIPPED_TIMEOUT, events=tuple(events))


def _delivered(d: SagaData, t: ShipmentDelivered) -> Decision:
    d2 = replace(d, shipment_id=d.shipment_id or t.shipment_id)
    return Decision(State.DELIVERED, d2, 0, None,
                    events=(Event("OrderDelivered", {"deliveredAt": t.delivered_at}),), outcome="DELIVERED")


def _reserve(d: SagaData) -> Command:
    return Command("ReserveStock", d.reservation_id, {"ttlSeconds": 900})


def _authorize(d: SagaData) -> Command:
    assert d.payment_id
    return Command("AuthorizePayment", d.payment_id)


def _commit(d: SagaData) -> Command:
    return Command("CommitReservation", d.reservation_id)


def _request_fulfilment(d: SagaData) -> Command:
    assert d.fulfilment_id
    return Command("RequestFulfilment", d.fulfilment_id, {"attempt": d.fulfilment_attempt})


def _capture(d: SagaData) -> Command:
    assert d.payment_id
    return Command("CapturePayment", d.payment_id, {"attempt": d.capture_attempt})


def customer_status(state: State) -> str:
    """Saga state -> customer-facing OrderStatus (orders.yaml). Semantic lock: names say what is true."""
    if state in PRE_DECISION:
        return "PENDING"
    if state in (State.AWAITING_FULFILMENT_ACK, State.FULFILLING, State.PACKED, State.CAPTURING):
        return "CONFIRMED"
    if state in (State.CANCELLING, State.CANCELLED):
        return "CANCELLED"
    return state.value  # SHIPPED, DELIVERED, NEEDS_ATTENTION
