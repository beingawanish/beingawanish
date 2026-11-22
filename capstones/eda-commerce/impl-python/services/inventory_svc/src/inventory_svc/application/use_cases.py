"""Inventory use cases. Every one runs inside the caller's unit of work (consumer record, HTTP
request or sweeper batch), so the stock change, the reservation row and the reply commit together.

Idempotency by business id (ADR-0006 layer 2): a resent command (new eventId, same reservationId or
restockId) re-emits the **original** reply and never repeats the stock change.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from edacommon.envelope import Causation
from edacommon.errors import DomainError
from edacommon.logging import get_logger
from inventory_svc.application import messages
from inventory_svc.application.ports import EventPublisher, InventoryRepository
from inventory_svc.domain.model import (
    CommitDecision,
    ReleaseDecision,
    Reservation,
    ReservationStatus,
    StockLine,
    decide_commit,
    decide_release,
    hold_until,
    merge_lines,
)

log = get_logger(__name__)


@dataclass
class Inventory:
    repo: InventoryRepository
    events: EventPublisher
    max_ttl: timedelta

    # ------------------------------------------------------------------------------- ReserveStock
    def reserve(self, *, order_id: str, reservation_id: str, lines: list[StockLine], ttl_seconds: int,
                now: datetime, command_expired: bool = False) -> None:
        existing = self.repo.get_reservation(reservation_id, for_update=True)
        if existing is not None:
            self._reanswer(existing, now)
            return
        merged = merge_lines(lines)
        if command_expired:
            # envelope.expiresAt passed: reply with a rejection instead of acting (Envelope doc).
            res = Reservation(reservation_id, order_id, ReservationStatus.REJECTED, merged, None, (),
                              reason="command expired", changed_at=now)
            self.repo.save_reservation(res, now)
            self.events.publish(messages.stock_rejected(res))
            return
        shortages = self.repo.try_hold(merged)
        if shortages:
            res = Reservation(reservation_id, order_id, ReservationStatus.REJECTED, merged, None, tuple(shortages),
                              changed_at=now)
            self.repo.save_reservation(res, now)
            self.events.publish(messages.stock_rejected(res))
            return
        res = Reservation(reservation_id, order_id, ReservationStatus.HELD, merged,
                          hold_until(now, ttl_seconds, self.max_ttl))
        self.repo.save_reservation(res, now)
        self.events.publish(messages.stock_reserved(res))
        self._publish_levels([line.sku for line in merged], now)

    def _reanswer(self, res: Reservation, now: datetime) -> None:
        """The original reply for a reservation we already decided."""
        if res.status in (ReservationStatus.HELD, ReservationStatus.COMMITTED):
            self.events.publish(messages.stock_reserved(res))
        elif res.status is ReservationStatus.REJECTED:
            self.events.publish(messages.stock_rejected(res))
        elif res.status is ReservationStatus.EXPIRED:
            self.events.publish(messages.expired(res, res.changed_at or now))
        else:
            self.events.publish(messages.released(res.order_id, res.reservation_id, res.reason or "released",
                                                  res.changed_at or now))

    # -------------------------------------------------------------------------- CommitReservation
    def commit(self, *, order_id: str, reservation_id: str, now: datetime) -> None:
        res = self.repo.get_reservation(reservation_id, for_update=True)
        decision = decide_commit(res, now)
        if decision is CommitDecision.UNKNOWN or res is None:
            # Nothing was ever reserved under this id: the honest answer is "it is gone".
            log.warning("commit for unknown reservation", reservation_id=reservation_id)
            ghost = Reservation(reservation_id, order_id, ReservationStatus.EXPIRED, (), None, changed_at=now)
            self.repo.save_reservation(ghost, now)
            self.events.publish(messages.expired(ghost, now))
            return
        if decision is CommitDecision.COMMIT:
            self.repo.allocate(res.lines)
            done = replace(res, status=ReservationStatus.COMMITTED, changed_at=now)
            self.repo.save_reservation(done, now)
            self.events.publish(messages.committed(done, now))
            self._publish_levels([line.sku for line in res.lines], now)
        elif decision is CommitDecision.EXPIRE_THEN_ANSWER_EXPIRED:
            self._expire(res, now)
        elif decision is CommitDecision.ANSWER_COMMITTED:
            self.events.publish(messages.committed(res, res.changed_at or now))
        elif decision is CommitDecision.ANSWER_EXPIRED:
            self.events.publish(messages.expired(res, res.changed_at or now))
        elif decision is CommitDecision.ANSWER_RELEASED:
            self.events.publish(messages.released(res.order_id, res.reservation_id, res.reason or "released",
                                                  res.changed_at or now))
        else:
            self.events.publish(messages.stock_rejected(res))

    # ------------------------------------------------------------------------- ReleaseReservation
    def release(self, *, order_id: str, reservation_id: str, reason: str, now: datetime) -> None:
        res = self.repo.get_reservation(reservation_id, for_update=True)
        decision = decide_release(res)
        if decision is ReleaseDecision.TOMBSTONE:
            tomb = Reservation(reservation_id, order_id, ReservationStatus.RELEASED, (), None, reason=reason,
                               changed_at=now)
            self.repo.save_reservation(tomb, now)
            self.events.publish(messages.released(order_id, reservation_id, reason, now))
            return
        assert res is not None
        if decision is ReleaseDecision.ANSWER_RELEASED:
            self.events.publish(messages.released(res.order_id, reservation_id, res.reason or reason,
                                                  res.changed_at or now))
            return
        if decision is ReleaseDecision.RELEASE_HELD:
            self.repo.release_held(res.lines)
        else:
            self.repo.return_allocated(res.lines)
        done = replace(res, status=ReservationStatus.RELEASED, reason=reason, changed_at=now)
        self.repo.save_reservation(done, now)
        self.events.publish(messages.released(res.order_id, reservation_id, reason, now))
        self._publish_levels([line.sku for line in res.lines], now)

    # ------------------------------------------------------------------------------- RestockItems
    def restock(self, *, order_id: str, return_id: str, restock_id: str, lines: list[StockLine], now: datetime) -> None:
        seen = self.repo.restock_seen(restock_id)
        if seen is not None:
            self.events.publish(messages.restocked(order_id, return_id, restock_id, seen, now))
            return
        merged = merge_lines(lines)
        self.repo.add_on_hand(merged)
        self.repo.record_restock(restock_id, order_id, return_id, merged, now)
        self.events.publish(messages.restocked(order_id, return_id, restock_id, merged, now))
        self._publish_levels([line.sku for line in merged], now)

    # ---------------------------------------------------------------------------- TTL sweeper job
    def expire_due(self, now: datetime, limit: int = 100) -> int:
        due = self.repo.due_expiries(now, limit)
        for res in due:
            self._expire(res, now, causation=Causation(correlation_id=res.order_id))
        return len(due)

    def _expire(self, res: Reservation, now: datetime, causation: Causation | None = None) -> None:
        self.repo.release_held(res.lines)
        done = replace(res, status=ReservationStatus.EXPIRED, changed_at=now)
        self.repo.save_reservation(done, now)
        self.events.publish(messages.expired(done, now, causation))
        self._publish_levels([line.sku for line in res.lines], now, causation)

    # -------------------------------------------------------------------------------- admin seed
    def set_stock(self, sku: str, on_hand: int, now: datetime) -> None:
        if on_hand < 0:
            raise DomainError("onHand must be >= 0", problem_type="validation-error", status=400)
        current = self.repo.levels([sku])
        if current and on_hand < current[0].reserved:
            raise DomainError(f"onHand {on_hand} is below the {current[0].reserved} units currently reserved",
                              problem_type="stock-below-reserved")
        self.repo.set_on_hand(sku, on_hand)
        self._publish_levels([sku], now)

    def _publish_levels(self, skus: list[str], now: datetime, causation: Causation | None = None) -> None:
        for level in self.repo.levels(skus):
            self.events.publish(messages.stock_level(level, now, causation))
