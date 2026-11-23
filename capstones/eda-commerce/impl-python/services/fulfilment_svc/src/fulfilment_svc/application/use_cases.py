"""Fulfilment use cases. Each one runs inside the caller's unit of work (a consumer record or one
warehouse event from the pump), so the row change and the reply commit together (outbox).

Idempotency by business id (ADR-0006 layer 2): a resent command (new eventId, same fulfilmentId or
returnId) re-emits the original reply and never repeats the warehouse side effect. The warehouse
itself also dedupes on fulfilmentId, so even a resubmission after a lost request creates one pick
order (architecture §5.8).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from edacommon.claimcheck import object_key
from edacommon.envelope import Causation
from edacommon.errors import DomainError, RetryLater
from edacommon.logging import get_logger

from fulfilment_svc.application import messages
from fulfilment_svc.application.ports import (
    EventPublisher,
    FulfilmentRepository,
    InspectionReport,
    ManifestStore,
    Warehouse,
    WarehouseEvent,
)
from fulfilment_svc.domain.model import (
    CancelDecision,
    DispatchDecision,
    Fulfilment,
    FulfilmentStatus,
    IntakeStatus,
    OrderLine,
    RequestDecision,
    ReturnIntake,
    ReturnLine,
    WarehouseStep,
    decide_cancel,
    decide_dispatch,
    decide_request,
    warehouse_step_applies,
)

log = get_logger(__name__)
MANIFEST_BUCKET = "packing-manifests"
MANIFEST_RETENTION = timedelta(days=90)  # bucket lifecycle rule (infra/minio/init.sh)


class CannotCancelDispatched(DomainError):
    """Past the pivot only a human decides (ADR-0015): the command goes to the DLQ."""

    problem_type = "fulfilment-already-dispatched"
    status = 409


@dataclass
class Fulfilments:
    repo: FulfilmentRepository
    warehouse: Warehouse
    manifests: ManifestStore
    events: EventPublisher

    # ------------------------------------------------------------------------ RequestFulfilment
    def request(
        self,
        *,
        fulfilment_id: str,
        order_id: str,
        lines: list[OrderLine],
        ship_to: dict[str, object],
        shipping_method: str,
        attempt: int,
        command_id: str,
        correlation_id: str,
        now: datetime,
    ) -> None:
        f = self.repo.get(fulfilment_id, for_update=True)
        decision = decide_request(f)
        if decision is RequestDecision.CREATE_AND_SUBMIT:
            new = Fulfilment(
                fulfilment_id=fulfilment_id,
                order_id=order_id,
                status=FulfilmentStatus.REQUESTED,
                lines=tuple(lines),
                ship_to=dict(ship_to),
                shipping_method=shipping_method,
                correlation_id=correlation_id,
                attempt=attempt,
                wms_submissions=1,
                last_command_id=command_id,
                version=1,
                created_at=now,
            )
            self.repo.save(new, now)
            # No reply yet: FulfilmentAccepted is sent when the warehouse acknowledges.
            self.warehouse.submit_pick_order(fulfilment_id=fulfilment_id, order_id=order_id, lines=new.lines, now=now)
            return
        assert f is not None
        if decision is RequestDecision.RESUBMIT:
            log.info("warehouse has not acknowledged; resubmitting", fulfilment_id=fulfilment_id, attempt=attempt)
            self.repo.save(
                f.bump(attempt=max(attempt, f.attempt), wms_submissions=f.wms_submissions + 1, last_command_id=command_id), now
            )
            self.warehouse.submit_pick_order(fulfilment_id=fulfilment_id, order_id=f.order_id, lines=f.lines, now=now)
        elif decision is RequestDecision.ANSWER_ACCEPTED:
            self.events.publish(messages.accepted(f))
        elif decision is RequestDecision.ANSWER_CANCELLED:
            self.events.publish(messages.cancelled(f))
        else:
            self.events.publish(messages.failed(f))

    # ------------------------------------------------------------------------- CancelFulfilment
    def cancel(self, *, fulfilment_id: str, order_id: str, reason: str, correlation_id: str, now: datetime) -> None:
        f = self.repo.get(fulfilment_id, for_update=True)
        decision = decide_cancel(f)
        if decision is CancelDecision.TOMBSTONE:
            tomb = Fulfilment(
                fulfilment_id=fulfilment_id,
                order_id=order_id,
                status=FulfilmentStatus.CANCELLED,
                lines=(),
                ship_to=None,
                shipping_method="STANDARD",
                correlation_id=correlation_id,
                cancelled_at=now,
                failure_detail=reason,
                version=1,
                created_at=now,
            )
            self.repo.save(tomb, now)
            self.events.publish(messages.cancelled(tomb))
            return
        assert f is not None
        if decision is CancelDecision.REFUSE_DISPATCHED:
            raise CannotCancelDispatched(f"fulfilment {fulfilment_id} was dispatched; it cannot be cancelled")
        if decision is CancelDecision.ANSWER_CANCELLED:
            self.events.publish(messages.cancelled(f if f.cancelled_at else f.bump(cancelled_at=f.failed_at or now)))
            return
        self.warehouse.cancel_pick_order(fulfilment_id)
        done = f.bump(status=FulfilmentStatus.CANCELLED, cancelled_at=now)
        self.repo.save(done, now)
        self.events.publish(messages.cancelled(done))

    # ------------------------------------------------------------------- warehouse progress (pump)
    def on_warehouse_event(self, ev: WarehouseEvent, now: datetime) -> bool | None:
        """Apply one WMS event. False: it no longer applies (replayed, or after a cancel). None: the
        fulfilment row is not visible yet (the submitting transaction has not committed): keep it."""
        f = self.repo.get(ev.fulfilment_id, for_update=True)
        if f is None:
            return None
        if not warehouse_step_applies(f, ev.step):
            log.info("warehouse event ignored", fulfilment_id=ev.fulfilment_id, step=ev.step.value)
            return False
        # Async replies keep their causation: the command that asked for the work.
        causation = Causation(correlation_id=f.correlation_id, causation_id=f.last_command_id)
        if ev.step is WarehouseStep.ACCEPTED:
            done = f.bump(
                status=FulfilmentStatus.ACCEPTED,
                warehouse_id=ev.warehouse_id,
                accepted_at=ev.at,
                estimated_dispatch_at=ev.estimated_dispatch_at,
            )
            self.repo.save(done, now)
            self.events.publish(messages.accepted(done, causation))
        elif ev.step is WarehouseStep.PICKED:
            done = f.bump(status=FulfilmentStatus.PICKED, picked_at=ev.at)
            self.repo.save(done, now)
            self.events.publish(messages.picked(done, causation))
        elif ev.step is WarehouseStep.PACKED:
            assert ev.manifest is not None, "a packed event always carries its manifest"
            # Object first, event second (ADR-0009). The key is derived from business ids and the
            # fulfilment's creation month, so a retry overwrites the same object.
            created = f.created_at or now
            key = object_key("fulfilment", created, f.order_id, f.fulfilment_id, "json")
            claim = self.manifests.put(MANIFEST_BUCKET, key, ev.manifest, "application/json", ev.at + MANIFEST_RETENTION)
            done = f.bump(status=FulfilmentStatus.PACKED, packed_at=ev.at, parcels=ev.parcels, manifest=claim)
            self.repo.save(done, now)
            self.events.publish(messages.packed(done, causation))
        else:
            done = f.bump(
                status=FulfilmentStatus.FAILED,
                failed_at=ev.at,
                failure_reason=ev.failure_reason or "STOCK_DAMAGED",
                failure_detail=ev.failure_detail,
            )
            self.repo.save(done, now)
            self.events.publish(messages.failed(done, causation))
        return True

    # ---------------------------------------------------------------- ShipmentCreated (OUTBOUND)
    def on_shipment_created(self, *, fulfilment_id: str, shipment_id: str, now: datetime) -> None:
        """Choreography with shipping-svc (ADR-0001): the label is booked, the parcel leaves."""
        f = self.repo.get(fulfilment_id, for_update=True)
        decision = decide_dispatch(f)
        if decision is DispatchDecision.DISPATCH:
            assert f is not None
            done = f.bump(status=FulfilmentStatus.DISPATCHED, shipment_id=shipment_id, dispatched_at=now)
            self.repo.save(done, now)
            self.events.publish(messages.dispatched(done))
        elif decision is DispatchDecision.ANSWER_DISPATCHED:
            assert f is not None
            self.events.publish(messages.dispatched(f))
        elif decision is DispatchDecision.NOT_PACKED:
            if f is None:
                # ShipmentCreated raced ahead of our own commit (different topics): wait for it.
                raise RetryLater(f"no fulfilment {fulfilment_id} yet")
            log.warning("shipment created before packing; ignored", fulfilment_id=fulfilment_id, status=f.status.value)
        else:
            log.warning("shipment created for a stopped fulfilment; label unused", fulfilment_id=fulfilment_id)

    # ------------------------------------------------------------------------------ ExpectReturn
    def expect_return(
        self,
        *,
        return_id: str,
        order_id: str,
        rma_number: str,
        lines: list[ReturnLine],
        expected_by: datetime,
        correlation_id: str,
        now: datetime,
    ) -> None:
        if self.repo.get_intake(return_id, for_update=True) is not None:
            return  # resend after a label timeout: nothing new to expect
        self.repo.save_intake(
            ReturnIntake(
                return_id=return_id,
                order_id=order_id,
                rma_number=rma_number,
                status=IntakeStatus.EXPECTED,
                lines=tuple(lines),
                expected_by=expected_by,
                correlation_id=correlation_id,
                version=1,
            ),
            now,
        )

    # ------------------------------------------------------------------ ShipmentDelivered (RETURN)
    def on_return_delivered(
        self, *, return_id: str, shipment_id: str, event_id: str, delivered_at: datetime, now: datetime
    ) -> None:
        r = self.repo.get_intake(return_id, for_update=True)
        if r is None:
            # ExpectReturn travels on another topic; let it arrive first (ADR-0007).
            raise RetryLater(f"return {return_id} is not expected yet")
        if r.status is not IntakeStatus.EXPECTED:
            return  # the carrier delivered once; shipping-svc already normalised duplicates
        done = r.bump(status=IntakeStatus.RECEIVED, shipment_id=shipment_id, received_at=delivered_at, received_event_id=event_id)
        self.repo.save_intake(done, now)
        self.events.publish(messages.return_received(done))
        self.warehouse.inspect_return(return_id=return_id, lines=r.lines, now=now)

    def on_inspection(self, report: InspectionReport, now: datetime) -> bool | None:
        r = self.repo.get_intake(report.return_id, for_update=True)
        if r is None:
            return None
        if r.status is not IntakeStatus.RECEIVED:
            return False
        done = r.bump(status=IntakeStatus.INSPECTED, results=report.results, inspected_at=report.at)
        self.repo.save_intake(done, now)
        self.events.publish(
            messages.return_inspected(done, Causation(correlation_id=r.correlation_id, causation_id=r.received_event_id))
        )
        return True
