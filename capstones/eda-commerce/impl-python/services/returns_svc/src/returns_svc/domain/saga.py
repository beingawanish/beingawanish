"""The returns saga as a pure transition function (architecture §6, ADR-0008). A forward-recovery saga:
after inspection nothing is compensated; every step is retried until it succeeds or a human decides.

``transition(state, data, attempts, trigger, now, policy, ids) -> Decision``

States and edges (architecture §6.1):

====================  ===========================================  ====================================
from                  trigger                                      to / effect
====================  ===========================================  ====================================
(new)                 POST /returns (eligible)                     REQUESTED / ReturnRequested
REQUESTED             CONTINUE, value <= auto-approve limit        AUTHORIZED / RMA, ReturnAuthorized
REQUESTED             CONTINUE, value > limit                      MANUAL_REVIEW (outcome MANUAL_REVIEW)
MANUAL_REVIEW         ops APPROVE / REJECT                         AUTHORIZED / REJECTED
AUTHORIZED            CONTINUE                                     AWAITING_PARCEL / IssueReturnLabel + ExpectReturn
AWAITING_PARCEL       ShipmentCreated(RETURN)                      (same) / store label ref
AWAITING_PARCEL       DEADLINE, label missing                      (same) / resend both commands
AWAITING_PARCEL       DEADLINE, parcelDueBy passed                 EXPIRED
AWAITING_PARCEL       ReturnReceived                               AWAITING_INSPECTION
AWAITING_INSPECTION   ReturnInspected, refund > 0                  SETTLING / RestockItems + RefundPayment
AWAITING_INSPECTION   ReturnInspected, refund = 0                  REJECTED / RestockItems if any restockable
SETTLING              RefundFailed retryable (1st-3rd)             (same) / resend after 1 min, 10 min, 1 h
SETTLING              RefundFailed non-retryable or 4th failure    REFUND_REVIEW (outcome MANUAL_REVIEW)
SETTLING              RefundSucceeded and ItemsRestocked           CLOSED / ReturnRefunded, ReturnClosed
REFUND_REVIEW         ops RETRY_REFUND                             SETTLING / RefundPayment (same refundId)
REFUND_REVIEW         ops CLOSE_WITHOUT_REFUND                     CLOSED / ReturnClosed(MANUAL_REVIEW)
REJECTED              CONTINUE (nothing to restock) / ItemsRestocked  CLOSED / ReturnRejected, ReturnClosed(REJECTED)
EXPIRED               CONTINUE                                     CLOSED / ReturnClosed(EXPIRED)
====================  ===========================================  ====================================

REQUESTED, AUTHORIZED, EXPIRED and REJECTED (with nothing pending) are pass-through states: the
application applies ``Continue`` right away, in the same transaction, so every edge of the diagram is a
row in ``saga_transition``. Replies are matched by business id (shipmentId, refundId, restockId); the
same refundId is reused for every attempt, so a "failed" attempt that succeeded at the PSP can never
refund twice (architecture §6.4).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, ClassVar

from returns_svc.domain.policy import Inspected, ReturnLine, Settlement, settle, value_minor

SAGA_TYPE = "RETURN"
REFUND_RETRY_SCHEDULE = (timedelta(minutes=1), timedelta(minutes=10), timedelta(hours=1))
LABEL_TIMEOUT = timedelta(minutes=10)
LABEL_TIMEOUT_MAX = timedelta(hours=1)
REFUND_REPLY_TIMEOUT = timedelta(minutes=5)
RESTOCK_TIMEOUT = timedelta(seconds=60)
RESTOCK_TIMEOUT_MAX = timedelta(minutes=16)


class State(StrEnum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    AWAITING_PARCEL = "AWAITING_PARCEL"
    AWAITING_INSPECTION = "AWAITING_INSPECTION"
    SETTLING = "SETTLING"
    REFUND_REVIEW = "REFUND_REVIEW"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


PASS_THROUGH = frozenset({State.REQUESTED, State.AUTHORIZED, State.EXPIRED})
WAITING_FOR_HUMAN = frozenset({State.MANUAL_REVIEW, State.REFUND_REVIEW})


class Outcome(StrEnum):
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass(frozen=True, slots=True)
class Policy:
    auto_approve_limit_minor: int = 50000
    parcel_due: timedelta = timedelta(days=14)


@dataclass(frozen=True, slots=True)
class Ids:
    new_id: Callable[[], str]
    rma_number: Callable[[], str]  # gapless per year; the application backs it with a locked counter


# ----------------------------------------------------------------------------------------- data
@dataclass(frozen=True, slots=True)
class SagaData:
    return_id: str
    order_id: str
    customer_id: str
    currency: str
    reason: str
    lines: tuple[ReturnLine, ...]
    shipping_fee_minor: int  # refundable on this return (0 unless merchant fault and first return)
    pickup_from: dict[str, Any]
    warehouse_id: str
    payment_id: str | None = None
    comment: str | None = None
    requested_at: str | None = None
    rma_number: str | None = None
    parcel_due_by: str | None = None
    shipment_id: str | None = None
    label: dict[str, Any] | None = None
    label_due_at: str | None = None
    label_resends: int = 0
    received: bool = False
    results: tuple[dict[str, Any], ...] = ()
    refund_minor: int = 0
    refund_id: str | None = None
    restock_id: str | None = None
    restock_lines: tuple[tuple[str, int], ...] = ()
    restock_done: bool = True
    restock_due_at: str | None = None
    restock_resends: int = 0
    refund_done: bool = False
    refund_failures: int = 0
    refund_due_at: str | None = None
    full_refund: bool = False
    outcome: str | None = None
    rejection_reason: str | None = None
    decisions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def value_minor(self) -> int:
        return value_minor(self.lines)

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["lines"] = [asdict(x) for x in self.lines]
        d["results"] = list(self.results)
        d["restock_lines"] = [list(x) for x in self.restock_lines]
        d["decisions"] = list(self.decisions)
        d["notes"] = list(self.notes)
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> SagaData:
        known = set(cls.__dataclass_fields__)
        v = {k: x for k, x in d.items() if k in known}
        v["lines"] = tuple(ReturnLine(**x) for x in v.get("lines", ()))
        v["results"] = tuple(v.get("results", ()))
        v["restock_lines"] = tuple((str(a), int(b)) for a, b in v.get("restock_lines", ()))
        v["decisions"] = tuple(v.get("decisions", ()))
        v["notes"] = tuple(v.get("notes", ()))
        return cls(**v)

    def note(self, text: str) -> SagaData:
        return replace(self, notes=(*self.notes[-19:], text))


def _at(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


# ------------------------------------------------------------------------------------- triggers
@dataclass(frozen=True, slots=True)
class Trigger:
    kind: ClassVar[str] = "TRIGGER"


@dataclass(frozen=True, slots=True)
class Continue(Trigger):
    kind: ClassVar[str] = "CONTINUE"


@dataclass(frozen=True, slots=True)
class Decide(Trigger):
    kind: ClassVar[str] = "OPERATOR"
    decision: str  # APPROVE | REJECT | RETRY_REFUND | CLOSE_WITHOUT_REFUND
    note: str | None = None


@dataclass(frozen=True, slots=True)
class LabelCreated(Trigger):
    kind: ClassVar[str] = "ShipmentCreated"
    shipment_id: str
    label: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LabelFailed(Trigger):
    kind: ClassVar[str] = "ShipmentException"
    shipment_id: str
    code: str


@dataclass(frozen=True, slots=True)
class ParcelReceived(Trigger):
    kind: ClassVar[str] = "ReturnReceived"


@dataclass(frozen=True, slots=True)
class ParcelInspected(Trigger):
    kind: ClassVar[str] = "ReturnInspected"
    results: tuple[Inspected, ...]


@dataclass(frozen=True, slots=True)
class Restocked(Trigger):
    kind: ClassVar[str] = "ItemsRestocked"
    restock_id: str


@dataclass(frozen=True, slots=True)
class RefundSucceeded(Trigger):
    kind: ClassVar[str] = "RefundSucceeded"
    refund_id: str


@dataclass(frozen=True, slots=True)
class RefundFailed(Trigger):
    kind: ClassVar[str] = "RefundFailed"
    refund_id: str
    retryable: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Deadline(Trigger):
    kind: ClassVar[str] = "DEADLINE"


@dataclass(frozen=True, slots=True)
class OperatorRetry(Trigger):
    kind: ClassVar[str] = "OPERATOR"


# ------------------------------------------------------------------------------------ decisions
@dataclass(frozen=True, slots=True)
class Command:
    name: str  # IssueReturnLabel | ExpectReturn | RestockItems | RefundPayment


@dataclass(frozen=True, slots=True)
class Event:
    name: str  # ReturnRequested | ReturnAuthorized | ReturnRejected | ReturnRefunded | ReturnClosed


@dataclass(frozen=True, slots=True)
class Decision:
    state: State
    data: SagaData
    attempts: int
    deadline: datetime | None
    commands: tuple[Command, ...] = ()
    events: tuple[Event, ...] = ()
    ignored: bool = False
    outcome: str | None = None  # counted in eda.saga.outcomes

    @property
    def terminal(self) -> bool:
        return self.state is State.CLOSED

    @property
    def needs_continue(self) -> bool:
        if self.state in PASS_THROUGH:
            return True
        return self.state is State.REJECTED and self.data.restock_done


def _ignore(s: State, d: SagaData, attempts: int, deadline: datetime | None) -> Decision:
    return Decision(s, d, attempts, deadline, ignored=True)


# ---------------------------------------------------------------------------------- the machine
def start(data: SagaData) -> Decision:
    """POST /returns passed eligibility: REQUESTED, emit ReturnRequested."""
    return Decision(State.REQUESTED, data, 0, None, events=(Event("ReturnRequested"),))


def transition(
    s: State, d: SagaData, attempts: int, t: Trigger, now: datetime, policy: Policy, ids: Ids, deadline: datetime | None = None
) -> Decision:
    if s is State.CLOSED:
        return _ignore(s, d.note(f"late {t.kind} after close"), attempts, None)

    if s is State.REQUESTED and isinstance(t, Continue):
        if d.value_minor > policy.auto_approve_limit_minor:
            return Decision(State.MANUAL_REVIEW, d, 0, None, outcome=Outcome.MANUAL_REVIEW)
        return _authorize(d, now, policy, ids)

    if s is State.MANUAL_REVIEW and isinstance(t, Decide):
        d2 = replace(d, decisions=(*d.decisions, f"{t.decision}: {t.note or ''}".strip()))
        if t.decision == "APPROVE":
            return _authorize(d2, now, policy, ids)
        if t.decision == "REJECT":
            return Decision(
                State.REJECTED, replace(d2, rejection_reason=f"rejected in review: {t.note or 'no reason given'}"), 0, None
            )
        return _ignore(s, d, attempts, deadline)

    if s is State.AUTHORIZED and isinstance(t, Continue):
        d2 = replace(d, shipment_id=d.shipment_id or ids.new_id(), label_due_at=(now + LABEL_TIMEOUT).isoformat())
        return Decision(
            State.AWAITING_PARCEL, d2, 0, _parcel_deadline(d2), commands=(Command("IssueReturnLabel"), Command("ExpectReturn"))
        )

    if s is State.AWAITING_PARCEL:
        return _awaiting_parcel(d, attempts, t, now, policy, ids, deadline)

    if s is State.AWAITING_INSPECTION:
        if isinstance(t, ParcelInspected):
            return _inspected(d, t, now, ids)
        if isinstance(t, LabelCreated) and t.shipment_id == d.shipment_id and d.label is None:
            return Decision(s, replace(d, label=t.label), attempts, deadline)
        return _ignore(s, d, attempts, deadline)

    if s is State.SETTLING:
        return _settling(d, attempts, t, now, deadline)

    if s is State.REFUND_REVIEW:
        if isinstance(t, Decide):
            d2 = replace(d, decisions=(*d.decisions, f"{t.decision}: {t.note or ''}".strip()))
            if t.decision == "RETRY_REFUND":
                d3 = replace(d2, refund_failures=0, refund_due_at=(now + REFUND_REPLY_TIMEOUT).isoformat())
                return Decision(State.SETTLING, d3, 0, _settling_deadline(d3), commands=(Command("RefundPayment"),))
            if t.decision == "CLOSE_WITHOUT_REFUND":
                d3 = replace(d2, outcome=Outcome.MANUAL_REVIEW)
                return Decision(State.CLOSED, d3, 0, None, events=(Event("ReturnClosed"),))
            return _ignore(s, d, attempts, deadline)
        if isinstance(t, Restocked) and t.restock_id == d.restock_id:
            return Decision(s, replace(d, restock_done=True, restock_due_at=None), attempts, None)
        if isinstance(t, RefundSucceeded) and t.refund_id == d.refund_id:
            # An earlier "failed" attempt went through after all: settle forward.
            return _maybe_close(replace(d, refund_done=True, refund_due_at=None), attempts, now)
        if isinstance(t, Deadline) and not d.restock_done:
            return _resend_restock(s, d, attempts, now)
        return _ignore(s, d, attempts, deadline)

    if s is State.REJECTED:
        if isinstance(t, Restocked) and t.restock_id == d.restock_id:
            return _close_rejected(replace(d, restock_done=True, restock_due_at=None))
        if isinstance(t, Continue) and d.restock_done:
            return _close_rejected(d)
        if isinstance(t, (Deadline, OperatorRetry)) and not d.restock_done:
            return _resend_restock(s, d, attempts, now)
        return _ignore(s, d, attempts, deadline)

    if s is State.EXPIRED and isinstance(t, Continue):
        return Decision(
            State.CLOSED, replace(d, outcome=Outcome.EXPIRED), 0, None, events=(Event("ReturnClosed"),), outcome=Outcome.EXPIRED
        )

    return _ignore(s, d, attempts, deadline)


# ---------------------------------------------------------------------------------- helpers
def _authorize(d: SagaData, now: datetime, policy: Policy, ids: Ids) -> Decision:
    d2 = replace(d, rma_number=d.rma_number or ids.rma_number(), parcel_due_by=(now + policy.parcel_due).isoformat())
    return Decision(State.AUTHORIZED, d2, 0, None, events=(Event("ReturnAuthorized"),))


def _parcel_deadline(d: SagaData) -> datetime | None:
    due = _at(d.parcel_due_by)
    label = _at(d.label_due_at) if d.label is None else None
    candidates = [x for x in (due, label) if x is not None]
    return min(candidates) if candidates else None


def _awaiting_parcel(
    d: SagaData, attempts: int, t: Trigger, now: datetime, policy: Policy, ids: Ids, deadline: datetime | None
) -> Decision:
    s = State.AWAITING_PARCEL
    if isinstance(t, LabelCreated) and t.shipment_id == d.shipment_id:
        if d.label is not None:
            return _ignore(s, d, attempts, deadline)
        d2 = replace(d, label=t.label, label_due_at=None)
        return Decision(s, d2, attempts, _parcel_deadline(d2))
    if isinstance(t, LabelFailed) and t.shipment_id == d.shipment_id:
        return Decision(s, d.note(f"label booking failed ({t.code}); resend on the label deadline"), attempts, deadline)
    if isinstance(t, ParcelReceived):
        return Decision(State.AWAITING_INSPECTION, replace(d, received=True), 0, None)
    if isinstance(t, ParcelInspected):
        # Received was reordered behind inspection (retry topic): inspection implies receipt.
        return _inspected(replace(d, received=True), t, now, ids)
    if isinstance(t, (Deadline, OperatorRetry)):
        due = _at(d.parcel_due_by)
        if isinstance(t, Deadline) and due is not None and now >= due:
            return Decision(State.EXPIRED, d, 0, None)
        if d.label is None or isinstance(t, OperatorRetry):
            n = d.label_resends + 1
            wait = min(LABEL_TIMEOUT * (2**n), LABEL_TIMEOUT_MAX)
            d2 = replace(d, label_resends=n, label_due_at=(now + wait).isoformat() if d.label is None else None)
            return Decision(
                s, d2, attempts + 1, _parcel_deadline(d2), commands=(Command("IssueReturnLabel"), Command("ExpectReturn"))
            )
        return _ignore(s, d, attempts, _parcel_deadline(d))
    return _ignore(s, d, attempts, deadline)


def _inspected(d: SagaData, t: ParcelInspected, now: datetime, ids: Ids) -> Decision:
    st: Settlement = settle(d.lines, t.results, d.reason, d.shipping_fee_minor)
    results = tuple(asdict(r) for r in t.results)
    base = replace(d, results=results, refund_minor=st.refund_minor, restock_lines=st.restock, full_refund=st.full)
    commands: list[Command] = []
    if st.restock:
        base = replace(
            base, restock_id=d.restock_id or ids.new_id(), restock_done=False, restock_due_at=(now + RESTOCK_TIMEOUT).isoformat()
        )
        commands.append(Command("RestockItems"))
    if st.refund_minor > 0:
        base = replace(base, refund_id=d.refund_id or ids.new_id(), refund_due_at=(now + REFUND_REPLY_TIMEOUT).isoformat())
        commands.append(Command("RefundPayment"))
        return Decision(State.SETTLING, base, 0, _settling_deadline(base), commands=tuple(commands))
    base = replace(base, rejection_reason="inspection found nothing refundable")
    return Decision(
        State.REJECTED, base, 0, _at(base.restock_due_at) if not base.restock_done else None, commands=tuple(commands)
    )


def _settling_deadline(d: SagaData) -> datetime | None:
    xs = [
        x
        for x in (_at(d.refund_due_at) if not d.refund_done else None, _at(d.restock_due_at) if not d.restock_done else None)
        if x
    ]
    return min(xs) if xs else None


def _settling(d: SagaData, attempts: int, t: Trigger, now: datetime, deadline: datetime | None) -> Decision:
    s = State.SETTLING
    if isinstance(t, Restocked) and t.restock_id == d.restock_id:
        if d.restock_done:
            return _ignore(s, d, attempts, deadline)
        return _maybe_close(replace(d, restock_done=True, restock_due_at=None), attempts, now)
    if isinstance(t, RefundSucceeded) and t.refund_id == d.refund_id:
        if d.refund_done:
            return _ignore(s, d, attempts, deadline)
        return _maybe_close(replace(d, refund_done=True, refund_due_at=None), attempts, now)
    if isinstance(t, RefundFailed) and t.refund_id == d.refund_id and not d.refund_done:
        n = d.refund_failures + 1
        if t.retryable and n <= len(REFUND_RETRY_SCHEDULE):
            d2 = replace(d, refund_failures=n, refund_due_at=(now + REFUND_RETRY_SCHEDULE[n - 1]).isoformat()).note(
                f"refund failed ({t.reason}); retry {n} in {REFUND_RETRY_SCHEDULE[n - 1]}"
            )
            return Decision(s, d2, attempts, _settling_deadline(d2))
        d2 = replace(d, refund_failures=n, refund_due_at=None).note(f"refund failed ({t.reason}); needs a decision")
        return Decision(
            State.REFUND_REVIEW, d2, 0, _at(d2.restock_due_at) if not d2.restock_done else None, outcome=Outcome.MANUAL_REVIEW
        )
    if isinstance(t, (Deadline, OperatorRetry)):
        commands: list[Command] = []
        d2 = d
        force = isinstance(t, OperatorRetry)
        if not d.refund_done and (force or (_at(d.refund_due_at) or now) <= now):
            d2 = replace(d2, refund_due_at=(now + REFUND_REPLY_TIMEOUT).isoformat())
            commands.append(Command("RefundPayment"))
        if not d.restock_done and (force or (_at(d.restock_due_at) or now) <= now):
            n = d.restock_resends + 1
            d2 = replace(
                d2, restock_resends=n, restock_due_at=(now + min(RESTOCK_TIMEOUT * (2**n), RESTOCK_TIMEOUT_MAX)).isoformat()
            )
            commands.append(Command("RestockItems"))
        if not commands:
            return _ignore(s, d, attempts, _settling_deadline(d))
        return Decision(s, d2, attempts + 1, _settling_deadline(d2), commands=tuple(commands))
    return _ignore(s, d, attempts, deadline)


def _resend_restock(s: State, d: SagaData, attempts: int, now: datetime) -> Decision:
    n = d.restock_resends + 1
    d2 = replace(d, restock_resends=n, restock_due_at=(now + min(RESTOCK_TIMEOUT * (2**n), RESTOCK_TIMEOUT_MAX)).isoformat())
    return Decision(s, d2, attempts + 1, _at(d2.restock_due_at), commands=(Command("RestockItems"),))


def _maybe_close(d: SagaData, attempts: int, now: datetime) -> Decision:
    if d.refund_done and d.restock_done:
        outcome = Outcome.REFUNDED if d.full_refund else Outcome.PARTIALLY_REFUNDED
        return Decision(
            State.CLOSED,
            replace(d, outcome=outcome),
            0,
            None,
            events=(Event("ReturnRefunded"), Event("ReturnClosed")),
            outcome=outcome,
        )
    return Decision(State.SETTLING, d, attempts, _settling_deadline(d))


def _close_rejected(d: SagaData) -> Decision:
    d2 = replace(d, outcome=Outcome.REJECTED)
    return Decision(State.CLOSED, d2, 0, None, events=(Event("ReturnRejected"), Event("ReturnClosed")), outcome=Outcome.REJECTED)


def api_status(state: State, d: SagaData) -> str:
    """Saga state -> the ``Return.status`` enum of returns.yaml."""
    if state is State.CLOSED:
        return {"REFUNDED": "REFUNDED", "PARTIALLY_REFUNDED": "PARTIALLY_REFUNDED", "EXPIRED": "EXPIRED"}.get(
            d.outcome or "", "REJECTED"
        )
    return {
        State.REQUESTED: "REQUESTED",
        State.AUTHORIZED: "AUTHORIZED",
        State.MANUAL_REVIEW: "MANUAL_REVIEW",
        State.AWAITING_PARCEL: "AWAITING_PARCEL",
        State.AWAITING_INSPECTION: "RECEIVED",
        State.SETTLING: "REFUNDING",
        State.REFUND_REVIEW: "MANUAL_REVIEW",
        State.REJECTED: "REJECTED",
        State.EXPIRED: "EXPIRED",
    }[state]


def counts_against_order(state: State, d: SagaData) -> bool:
    """Quantities of a return that never reached the warehouse go back to "returnable"."""
    if state is State.EXPIRED or d.outcome == Outcome.EXPIRED:
        return False
    rejected = state is State.REJECTED or (state is State.CLOSED and d.outcome == Outcome.REJECTED)
    return not (rejected and not d.received)
