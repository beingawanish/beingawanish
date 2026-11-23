"""Fulfilment domain: warehouse orders (pick, pack, dispatch) and returns intake. Pure: no I/O, no clock.

Outbound lifecycle (one row per ``fulfilmentId``, minted by order-svc)::

    REQUESTED --WMS accepted--> ACCEPTED --picked--> PICKED --packed--> PACKED --ShipmentCreated--> DISPATCHED
        |                          |                   |                  |
        +---- CancelFulfilment ----+-------------------+------------------+--> CANCELLED
        +---- WMS failure ---------+-------------------+------------------+--> FAILED

Rules (architecture §5.8, ADR-0006 layer 2):

* ``RequestFulfilment`` is safe to resend. An unknown id creates the warehouse order; a known id that
  the warehouse has not acknowledged yet is pushed to the warehouse again (it may have lost it); a known
  id the warehouse already acknowledged re-emits the **original** reply and never creates a second
  pick order.
* ``CancelFulfilment`` for an unknown id writes a tombstone, so a late ``RequestFulfilment`` (through a
  retry topic) cannot start picking a cancelled order. A dispatched order cannot be cancelled: past the
  pivot only a human decides (ADR-0015).

Returns intake: ``EXPECTED`` (ExpectReturn) -> ``RECEIVED`` (carrier delivered the return parcel)
-> ``INSPECTED`` (one outcome per returned unit, grouped per line and outcome).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any


class FulfilmentStatus(StrEnum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    PICKED = "PICKED"
    PACKED = "PACKED"
    DISPATCHED = "DISPATCHED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


ACKNOWLEDGED = frozenset(
    {FulfilmentStatus.ACCEPTED, FulfilmentStatus.PICKED, FulfilmentStatus.PACKED, FulfilmentStatus.DISPATCHED}
)
CANCELLABLE = frozenset({FulfilmentStatus.REQUESTED, FulfilmentStatus.ACCEPTED, FulfilmentStatus.PICKED, FulfilmentStatus.PACKED})


class FailureReason(StrEnum):
    STOCK_DAMAGED = "STOCK_DAMAGED"
    STOCK_NOT_FOUND = "STOCK_NOT_FOUND"
    ADDRESS_UNSERVICEABLE = "ADDRESS_UNSERVICEABLE"


@dataclass(frozen=True, slots=True)
class OrderLine:
    line_id: str
    sku: str
    product_name: str
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity} for line {self.line_id}")


@dataclass(frozen=True, slots=True)
class Parcel:
    parcel_id: str
    weight_grams: int
    length_mm: int
    width_mm: int
    height_mm: int


@dataclass(frozen=True, slots=True)
class Fulfilment:
    fulfilment_id: str
    order_id: str
    status: FulfilmentStatus
    lines: tuple[OrderLine, ...]
    ship_to: dict[str, Any] | None
    shipping_method: str
    correlation_id: str
    attempt: int = 1
    wms_submissions: int = 0
    warehouse_id: str | None = None
    accepted_at: datetime | None = None
    estimated_dispatch_at: datetime | None = None
    picked_at: datetime | None = None
    packed_at: datetime | None = None
    dispatched_at: datetime | None = None
    cancelled_at: datetime | None = None
    failed_at: datetime | None = None
    failure_reason: str | None = None
    failure_detail: str | None = None
    manifest: dict[str, Any] | None = None  # ClaimCheck, Avro shape
    parcels: tuple[Parcel, ...] = ()
    shipment_id: str | None = None
    last_command_id: str | None = None
    version: int = 0
    created_at: datetime | None = None

    def bump(self, **changes: Any) -> Fulfilment:
        return replace(self, version=self.version + 1, **changes)


# --------------------------------------------------------------------------------- decisions
class RequestDecision(StrEnum):
    CREATE_AND_SUBMIT = "CREATE_AND_SUBMIT"
    RESUBMIT = "RESUBMIT"  # known, warehouse never acknowledged: push again (it may have lost it)
    ANSWER_ACCEPTED = "ANSWER_ACCEPTED"  # the original reply, no second pick order
    ANSWER_CANCELLED = "ANSWER_CANCELLED"
    ANSWER_FAILED = "ANSWER_FAILED"


def decide_request(f: Fulfilment | None) -> RequestDecision:
    if f is None:
        return RequestDecision.CREATE_AND_SUBMIT
    if f.status is FulfilmentStatus.REQUESTED:
        return RequestDecision.RESUBMIT
    if f.status in ACKNOWLEDGED:
        return RequestDecision.ANSWER_ACCEPTED
    if f.status is FulfilmentStatus.CANCELLED:
        return RequestDecision.ANSWER_CANCELLED
    return RequestDecision.ANSWER_FAILED


class CancelDecision(StrEnum):
    TOMBSTONE = "TOMBSTONE"
    CANCEL = "CANCEL"
    ANSWER_CANCELLED = "ANSWER_CANCELLED"  # already cancelled, or failed (nothing left to stop)
    REFUSE_DISPATCHED = "REFUSE_DISPATCHED"


def decide_cancel(f: Fulfilment | None) -> CancelDecision:
    if f is None:
        return CancelDecision.TOMBSTONE
    if f.status in CANCELLABLE:
        return CancelDecision.CANCEL
    if f.status is FulfilmentStatus.DISPATCHED:
        return CancelDecision.REFUSE_DISPATCHED
    return CancelDecision.ANSWER_CANCELLED


class WarehouseStep(StrEnum):
    ACCEPTED = "ACCEPTED"
    PICKED = "PICKED"
    PACKED = "PACKED"
    FAILED = "FAILED"


_NEXT: dict[WarehouseStep, frozenset[FulfilmentStatus]] = {
    WarehouseStep.ACCEPTED: frozenset({FulfilmentStatus.REQUESTED}),
    WarehouseStep.PICKED: frozenset({FulfilmentStatus.ACCEPTED}),
    WarehouseStep.PACKED: frozenset({FulfilmentStatus.PICKED}),
    WarehouseStep.FAILED: frozenset({FulfilmentStatus.REQUESTED, FulfilmentStatus.ACCEPTED, FulfilmentStatus.PICKED}),
}


def warehouse_step_applies(f: Fulfilment | None, step: WarehouseStep) -> bool:
    """Warehouse progress only moves forward and never revives a cancelled or failed order. Anything
    else (a replayed WMS event, progress after a cancel) is ignored."""
    return f is not None and f.status in _NEXT[step]


class DispatchDecision(StrEnum):
    DISPATCH = "DISPATCH"
    ANSWER_DISPATCHED = "ANSWER_DISPATCHED"  # shipping re-emitted ShipmentCreated
    NOT_PACKED = "NOT_PACKED"  # cannot happen in the choreography; recorded and ignored
    IGNORE_STOPPED = "IGNORE_STOPPED"  # cancelled or failed: the label is not used


def decide_dispatch(f: Fulfilment | None) -> DispatchDecision:
    if f is None or f.status in (FulfilmentStatus.REQUESTED, FulfilmentStatus.ACCEPTED, FulfilmentStatus.PICKED):
        return DispatchDecision.NOT_PACKED
    if f.status is FulfilmentStatus.PACKED:
        return DispatchDecision.DISPATCH
    if f.status is FulfilmentStatus.DISPATCHED:
        return DispatchDecision.ANSWER_DISPATCHED
    return DispatchDecision.IGNORE_STOPPED


# ------------------------------------------------------------------------------ returns intake
class IntakeStatus(StrEnum):
    EXPECTED = "EXPECTED"
    RECEIVED = "RECEIVED"
    INSPECTED = "INSPECTED"


class InspectionOutcome(StrEnum):
    RESTOCKABLE = "RESTOCKABLE"
    DAMAGED = "DAMAGED"
    MISSING = "MISSING"


@dataclass(frozen=True, slots=True)
class ReturnLine:
    line_id: str
    sku: str
    quantity: int


@dataclass(frozen=True, slots=True)
class InspectionResult:
    line_id: str
    sku: str
    quantity: int
    outcome: InspectionOutcome
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ReturnIntake:
    return_id: str
    order_id: str
    rma_number: str
    status: IntakeStatus
    lines: tuple[ReturnLine, ...]
    expected_by: datetime
    correlation_id: str
    shipment_id: str | None = None
    received_at: datetime | None = None
    received_event_id: str | None = None
    results: tuple[InspectionResult, ...] = field(default_factory=tuple)
    inspected_at: datetime | None = None
    version: int = 0

    def bump(self, **changes: Any) -> ReturnIntake:
        return replace(self, version=self.version + 1, **changes)


def group_outcomes(line: ReturnLine, unit_outcomes: list[InspectionOutcome]) -> list[InspectionResult]:
    """One result per (line, outcome), in a stable order. Units the warehouse did not report are MISSING."""
    counts: dict[InspectionOutcome, int] = {}
    for o in unit_outcomes[: line.quantity]:
        counts[o] = counts.get(o, 0) + 1
    missing = line.quantity - sum(counts.values())
    if missing > 0:
        counts[InspectionOutcome.MISSING] = counts.get(InspectionOutcome.MISSING, 0) + missing
    return [InspectionResult(line.line_id, line.sku, q, o) for o in InspectionOutcome if (q := counts.get(o, 0)) > 0]


def plan_parcels(
    lines: tuple[OrderLine, ...], parcel_id_of: Callable[[int], str], *, grams_per_unit: int = 450, max_grams: int = 20000
) -> tuple[Parcel, ...]:
    """Split units into parcels of at most ``max_grams`` (carriers refuse heavier ones)."""
    units = sum(x.quantity for x in lines)
    total = max(units * grams_per_unit, 1)
    parcels: list[Parcel] = []
    i = 0
    while total > 0:
        w = min(total, max_grams)
        parcels.append(Parcel(parcel_id_of(i), w, 400, 300, 150 if w < 5000 else 300))
        total -= w
        i += 1
    return tuple(parcels)
