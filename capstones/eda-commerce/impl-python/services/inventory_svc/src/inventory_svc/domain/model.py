"""Inventory domain: stock levels and reservations with a TTL (ADR-0016). Pure: no I/O, no clock.

Stock arithmetic (one row per SKU):

* reserve  (HELD):        ``reserved += q``                      - units held, not yet sold
* commit   (COMMITTED):   ``on_hand -= q; reserved -= q``         - units allocated to the order
* release a HELD one:     ``reserved -= q``
* release a COMMITTED one:``on_hand += q``                       - allocated units go back on the shelf
* expire   (EXPIRED):     ``reserved -= q``
* restock:                ``on_hand += q``

``available = on_hand - reserved`` and is never negative: reservations use a conditional update
(``WHERE on_hand - reserved >= q``), so the database enforces the invariant under concurrency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

LOW_STOCK_THRESHOLD = 5


class ReservationStatus(StrEnum):
    HELD = "HELD"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class StockLine:
    sku: str
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity} for {self.sku}")


@dataclass(frozen=True, slots=True)
class Shortage:
    sku: str
    requested: int
    available: int


@dataclass(frozen=True, slots=True)
class StockLevel:
    sku: str
    on_hand: int
    reserved: int
    version: int

    @property
    def available(self) -> int:
        return max(self.on_hand - self.reserved, 0)


@dataclass(frozen=True, slots=True)
class Reservation:
    reservation_id: str
    order_id: str
    status: ReservationStatus
    lines: tuple[StockLine, ...]
    expires_at: datetime | None
    shortages: tuple[Shortage, ...] = field(default_factory=tuple)
    reason: str | None = None
    changed_at: datetime | None = None  # committed / released / expired at

    def is_expired(self, now: datetime) -> bool:
        return self.status is ReservationStatus.HELD and self.expires_at is not None and now >= self.expires_at


def merge_lines(lines: list[StockLine]) -> tuple[StockLine, ...]:
    """One line per SKU, sorted, so conditional updates always lock rows in the same order
    (no deadlocks between two reservations that share SKUs)."""
    totals: dict[str, int] = {}
    for line in lines:
        totals[line.sku] = totals.get(line.sku, 0) + line.quantity
    return tuple(StockLine(sku, q) for sku, q in sorted(totals.items()))


def hold_until(now: datetime, requested_ttl_s: int, max_ttl: timedelta) -> datetime:
    """The command asks for a TTL; the service caps it with RESERVATION_TTL (drills shorten it)."""
    ttl = timedelta(seconds=max(requested_ttl_s, 1))
    return now + min(ttl, max_ttl)


class CommitDecision(StrEnum):
    COMMIT = "COMMIT"  # HELD and still valid
    EXPIRE_THEN_ANSWER_EXPIRED = "EXPIRE_THEN_ANSWER_EXPIRED"  # HELD but past its TTL (sweeper not there yet)
    ANSWER_COMMITTED = "ANSWER_COMMITTED"  # resend after a successful commit
    ANSWER_EXPIRED = "ANSWER_EXPIRED"
    ANSWER_RELEASED = "ANSWER_RELEASED"
    ANSWER_REJECTED = "ANSWER_REJECTED"
    UNKNOWN = "UNKNOWN"


def decide_commit(res: Reservation | None, now: datetime) -> CommitDecision:
    if res is None:
        return CommitDecision.UNKNOWN
    if res.status is ReservationStatus.HELD:
        return CommitDecision.EXPIRE_THEN_ANSWER_EXPIRED if res.is_expired(now) else CommitDecision.COMMIT
    return {
        ReservationStatus.COMMITTED: CommitDecision.ANSWER_COMMITTED,
        ReservationStatus.EXPIRED: CommitDecision.ANSWER_EXPIRED,
        ReservationStatus.RELEASED: CommitDecision.ANSWER_RELEASED,
        ReservationStatus.REJECTED: CommitDecision.ANSWER_REJECTED,
    }[res.status]


class ReleaseDecision(StrEnum):
    RELEASE_HELD = "RELEASE_HELD"
    RETURN_ALLOCATED = "RETURN_ALLOCATED"
    TOMBSTONE = "TOMBSTONE"  # unknown reservation: remember it was released
    ANSWER_RELEASED = "ANSWER_RELEASED"  # already released, expired or rejected: nothing held


def decide_release(res: Reservation | None) -> ReleaseDecision:
    """Release is the compensation for held *and* committed reservations; releasing twice is a no-op
    (ADR-0016). Unknown ids get a tombstone so a late ReserveStock cannot hold stock afterwards."""
    if res is None:
        return ReleaseDecision.TOMBSTONE
    if res.status is ReservationStatus.HELD:
        return ReleaseDecision.RELEASE_HELD
    if res.status is ReservationStatus.COMMITTED:
        return ReleaseDecision.RETURN_ALLOCATED
    return ReleaseDecision.ANSWER_RELEASED


def availability(level: StockLevel | None) -> str:
    if level is None:
        return "UNKNOWN"
    if level.available <= 0:
        return "OUT_OF_STOCK"
    if level.available <= LOW_STOCK_THRESHOLD:
        return "LOW_STOCK"
    return "IN_STOCK"
