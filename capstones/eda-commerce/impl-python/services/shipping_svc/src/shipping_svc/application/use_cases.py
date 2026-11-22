"""Shipping use cases. Each runs inside the caller's unit of work: a consumer record, one booking retry,
or one stored carrier webhook.

* Outbound (choreography with fulfilment-svc, ADR-0001): ``OrderPacked`` -> book -> label PDF to
  object storage -> ``ShipmentCreated(OUTBOUND)``. shipping-svc mints the shipmentId; one shipment per
  fulfilmentId, so a redelivered ``OrderPacked`` re-emits the original reply.
* Returns (command from returns-svc): ``IssueReturnLabel`` carries a shipmentId minted by the caller,
  so the command is idempotent.
* The carrier is called inside the transaction; that is safe because booking is idempotent on
  shipmentId (ADR-0006 layer 3), the same trade-off payment-svc makes with the PSP.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from edacommon.claimcheck import object_key
from edacommon.envelope import Causation
from edacommon.logging import get_logger

from shipping_svc.application import messages
from shipping_svc.application.ports import (
    Carrier,
    CarrierUnavailable,
    EventPublisher,
    LabelData,
    LabelRenderer,
    LabelStore,
    ShipmentRepository,
    TrackingUpdate,
)
from shipping_svc.domain.model import (
    LABEL_RETENTION,
    Direction,
    Emit,
    Shipment,
    ShipmentStatus,
    after_failed_booking,
    exception_code,
    normalise,
)

log = get_logger(__name__)
LABEL_BUCKET = "shipping-labels"


@dataclass
class Shipments:
    repo: ShipmentRepository
    carrier: Carrier
    renderer: LabelRenderer
    labels: LabelStore
    events: EventPublisher
    mint: Callable[[], str]  # UUIDv7 for outbound shipmentIds

    # ---------------------------------------------------------------------- OrderPacked (outbound)
    def on_order_packed(
        self,
        *,
        order_id: str,
        fulfilment_id: str,
        warehouse_id: str,
        ship_to: dict[str, Any],
        parcel_count: int,
        shipping_method: str,
        trigger_id: str,
        correlation_id: str,
        now: datetime,
    ) -> None:
        existing = self.repo.by_fulfilment(fulfilment_id, for_update=True)
        if existing is not None:
            self._reanswer(existing)
            return
        s = Shipment(
            shipment_id=self.mint(),
            order_id=order_id,
            direction=Direction.OUTBOUND,
            address=dict(ship_to),
            status=ShipmentStatus.BOOKING_PENDING,
            correlation_id=correlation_id,
            fulfilment_id=fulfilment_id,
            warehouse_id=warehouse_id,
            parcel_count=max(parcel_count, 1),
            shipping_method=shipping_method,
            causation_id=trigger_id,
            created_at=now,
        )
        self._attempt(s, now)

    # ------------------------------------------------------------------------ IssueReturnLabel
    def issue_return_label(
        self,
        *,
        order_id: str,
        return_id: str,
        shipment_id: str,
        pickup_from: dict[str, Any],
        to_warehouse_id: str,
        trigger_id: str,
        correlation_id: str,
        now: datetime,
    ) -> None:
        existing = self.repo.get(shipment_id, for_update=True)
        if existing is not None:
            if existing.status is ShipmentStatus.BOOKING_FAILED:
                # The saga resent after its label timeout: forward recovery, start the attempts again.
                self._attempt(existing.bump(booking_attempts=0, causation_id=trigger_id), now)
            else:
                self._reanswer(existing)
            return
        s = Shipment(
            shipment_id=shipment_id,
            order_id=order_id,
            direction=Direction.RETURN,
            address=dict(pickup_from),
            status=ShipmentStatus.BOOKING_PENDING,
            correlation_id=correlation_id,
            return_id=return_id,
            warehouse_id=to_warehouse_id,
            causation_id=trigger_id,
            created_at=now,
        )
        self._attempt(s, now)

    # -------------------------------------------------------------------------- booking retries
    def retry_due_bookings(self, now: datetime, limit: int = 50) -> int:
        due = self.repo.due_bookings(now, limit)
        for s in due:
            self._attempt(s, now)
        return len(due)

    def _attempt(self, s: Shipment, now: datetime) -> None:
        causation = Causation(correlation_id=s.correlation_id, causation_id=s.causation_id)
        try:
            booking = self.carrier.book(
                shipment_id=s.shipment_id, direction=s.direction, address=s.address, parcel_count=s.parcel_count
            )
        except CarrierUnavailable as exc:
            attempts = s.booking_attempts + 1
            plan = after_failed_booking(attempts, now)
            if plan.give_up:
                failed = s.bump(status=ShipmentStatus.BOOKING_FAILED, booking_attempts=attempts, next_attempt_at=None)
                self.repo.save(failed, now)
                self.events.publish(
                    messages.exception(failed, "BOOKING_FAILED", now, f"carrier booking failed {attempts} times", None, causation)
                )
                log.error("carrier booking failed; giving up", shipment_id=s.shipment_id, attempts=attempts)
            else:
                self.repo.save(s.bump(booking_attempts=attempts, next_attempt_at=plan.next_attempt_at), now)
                log.warning("carrier booking failed; will retry", shipment_id=s.shipment_id, attempts=attempts, error=exc)
            return
        booked_at = now
        pdf = self.renderer.render(
            LabelData(
                shipment_id=s.shipment_id,
                order_id=s.order_id,
                direction=s.direction,
                carrier=booking.carrier,
                tracking_number=booking.tracking_number,
                address=s.address,
                parcel_count=s.parcel_count,
                shipping_method=s.shipping_method,
                booked_at=booked_at,
            )
        )
        # Object first, event second (ADR-0009); the key is deterministic from business ids.
        key = object_key("shipping", s.created_at or now, s.order_id, s.shipment_id, "pdf")
        label = self.labels.put(LABEL_BUCKET, key, pdf, "application/pdf", booked_at + LABEL_RETENTION)
        done = s.bump(
            status=ShipmentStatus.BOOKED,
            carrier=booking.carrier,
            tracking_number=booking.tracking_number,
            label=label,
            booked_at=booked_at,
            booking_attempts=s.booking_attempts + 1,
            next_attempt_at=None,
        )
        self.repo.save(done, now)
        self.events.publish(messages.created(done, causation))

    def _reanswer(self, s: Shipment) -> None:
        if s.status is ShipmentStatus.BOOKED:
            self.events.publish(messages.created(s))
        # BOOKING_PENDING: the retry schedule is already on it. BOOKING_FAILED (outbound): a human.

    # -------------------------------------------------------------------- carrier webhook updates
    def on_tracking(self, u: TrackingUpdate, now: datetime) -> tuple[str, str | None]:
        """Apply one stored carrier update. Returns (outcome, shipment_id) for the audit row."""
        s = self.repo.by_tracking_number(u.tracking_number, for_update=True)
        if s is None:
            return "UNKNOWN_SHIPMENT", None
        d = normalise(s.tracking_rank, u.status)
        # A webhook is an HTTP request from outside: no causing event (Envelope doc); same flow.
        causation = Causation(correlation_id=s.correlation_id)
        if d.emit is None:
            if d.new_rank != s.tracking_rank:
                self.repo.save(s.bump(tracking_rank=d.new_rank), now)
            return "STORED_ONLY", s.shipment_id
        if d.emit is Emit.EXCEPTION:
            done = s.bump()
            self.repo.save(done, now)
            code = exception_code(u.exception_code)
            self.events.publish(messages.exception(done, code, u.occurred_at, u.location, u.carrier_event_id, causation))
        elif d.emit is Emit.DELIVERED:
            done = s.bump(tracking_rank=d.new_rank, delivered_at=u.occurred_at)
            self.repo.save(done, now)
            self.events.publish(messages.delivered(done, u.carrier_event_id, u.occurred_at, causation))
        else:
            done = s.bump(tracking_rank=d.new_rank)
            self.repo.save(done, now)
            self.events.publish(messages.in_transit(done, u.carrier_event_id, u.occurred_at, u.location, causation))
        return f"EMITTED_{d.emit.value}", s.shipment_id
