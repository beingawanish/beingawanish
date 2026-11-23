"""Pure tests: tracking normalisation, booking retry schedule, fake carrier behaviour."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from itertools import permutations

import pytest
from shipping_svc.adapters.outbound.carrier.acl import to_update, validate
from shipping_svc.adapters.outbound.carrier.fake.carrier import FakeCarrier, FakeCarrierConfig, tracking_number_for
from shipping_svc.application.ports import CarrierUnavailable
from shipping_svc.domain.model import (
    BOOKING_BACKOFF,
    MAX_BOOKING_ATTEMPTS,
    CarrierStatus,
    Direction,
    Emit,
    after_failed_booking,
    exception_code,
    normalise,
)

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
S = CarrierStatus


def test_forward_moves_emit_backward_moves_store_only() -> None:
    assert normalise(0, S.PICKED_UP).emit is Emit.IN_TRANSIT
    assert normalise(1, S.IN_TRANSIT) == normalise(1, S.IN_TRANSIT)
    assert normalise(2, S.OUT_FOR_DELIVERY).emit is Emit.IN_TRANSIT
    d = normalise(0, S.DELIVERED)
    assert d.emit is Emit.DELIVERED and d.new_rank == 4
    back = normalise(4, S.IN_TRANSIT)
    assert back.emit is None and back.new_rank == 4
    assert normalise(2, S.IN_TRANSIT).emit is None  # same rank twice
    assert normalise(4, S.EXCEPTION).emit is Emit.EXCEPTION  # always
    assert normalise(0, S.LABEL_CREATED).emit is None


@pytest.mark.parametrize("order", list(permutations([S.PICKED_UP, S.IN_TRANSIT, S.OUT_FOR_DELIVERY, S.DELIVERED])))
def test_any_arrival_order_gives_monotonic_unique_events_and_one_delivery(order: tuple[CarrierStatus, ...]) -> None:
    rank, emitted = 0, []
    for st in [*order, *order]:  # every webhook twice
        d = normalise(rank, st)
        if d.emit:
            emitted.append((d.emit, d.new_rank))
        rank = d.new_rank
    ranks = [r for _, r in emitted]
    assert ranks == sorted(set(ranks)), "strictly increasing, no repeats"
    assert [e for e, _ in emitted].count(Emit.DELIVERED) == 1


def test_booking_retry_schedule_then_give_up() -> None:
    assert after_failed_booking(1, NOW).next_attempt_at == NOW + BOOKING_BACKOFF[0]
    assert after_failed_booking(4, NOW).next_attempt_at == NOW + timedelta(hours=1)
    assert after_failed_booking(MAX_BOOKING_ATTEMPTS, NOW).give_up


def test_exception_codes_unknown_passthrough() -> None:
    assert exception_code("LOST") == "LOST"
    assert exception_code("ALIENS") == "UNKNOWN"
    assert exception_code(None) == "UNKNOWN"


def test_acl_validates_and_translates() -> None:
    p = {"carrierEventId": "c1", "trackingNumber": "FC1", "status": "IN_TRANSIT", "occurredAt": "2026-11-18T09:10:00.000Z"}
    assert validate(p) == "IN_TRANSIT"
    u = to_update(p, NOW)
    assert u.status is S.IN_TRANSIT and u.occurred_at.tzinfo is not None
    with pytest.raises(ValueError, match="TELEPORTED"):
        validate({**p, "status": "TELEPORTED"})
    with pytest.raises(KeyError):
        validate({**p, "trackingNumber": None})


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def carrier(**kw: object) -> tuple[FakeCarrier, list[dict[str, object]], Clock]:
    sent: list[dict[str, object]] = []
    mono = Clock()
    base = FakeCarrierConfig(duplicateRate=0, outOfOrderRate=0, exceptionRate=0, stepDelayMs=1000, bookingFailureRate=0)
    c = FakeCarrier(
        base.merged(dict(kw)),
        url="u",
        secret="s",
        send=lambda u, h, raw: sent.append(json.loads(raw)),
        seed=5,
        wall_clock=lambda: NOW,
        monotonic=mono,
    )
    return c, sent, mono


def test_booking_is_idempotent_and_tracking_number_deterministic() -> None:
    c, _, _ = carrier()
    b1 = c.book(shipment_id="s1", direction=Direction.OUTBOUND, address={}, parcel_count=1)
    b2 = c.book(shipment_id="s1", direction=Direction.OUTBOUND, address={}, parcel_count=1)
    assert b1 == b2 and b1.tracking_number == tracking_number_for("s1")


def test_booking_failures_are_raised() -> None:
    c, _, _ = carrier(bookingFailureRate=1.0)
    with pytest.raises(CarrierUnavailable):
        c.book(shipment_id="s1", direction=Direction.RETURN, address={}, parcel_count=1)


def test_progress_follows_step_delay_and_duplicates_resend_same_id() -> None:
    c, sent, mono = carrier(duplicateRate=1.0)
    t = c.book(shipment_id="s1", direction=Direction.OUTBOUND, address={}, parcel_count=1).tracking_number
    assert c.due() == []
    mono.t = 1.0
    for raw in c.due():
        c.deliver(raw)
    assert [s["status"] for s in sent] == ["PICKED_UP", "PICKED_UP"] and sent[0]["carrierEventId"] == sent[1]["carrierEventId"]
    assert sent[0]["trackingNumber"] == t
    mono.t = 10
    for raw in c.due():
        c.deliver(raw)
    assert [s["status"] for s in sent][::2] == ["PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"]


def test_out_of_order_swaps_send_times_but_not_carrier_timestamps() -> None:
    c, sent, _ = carrier(outOfOrderRate=1.0)
    c.book(shipment_id="s1", direction=Direction.OUTBOUND, address={}, parcel_count=1)
    c.flush()
    statuses = [s["status"] for s in sent]
    assert sorted(statuses) == sorted(["PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"])
    assert statuses != ["PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"]
    by_time = sorted(sent, key=lambda s: str(s["occurredAt"]))
    assert [s["status"] for s in by_time] == ["PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"]


def test_advance_without_auto_progress() -> None:
    c, sent, _ = carrier(stepDelayMs=0, exceptionRate=0)
    t = c.book(shipment_id="s1", direction=Direction.OUTBOUND, address={}, parcel_count=1).tracking_number
    assert c.due() == []
    assert c.advance(t)
    for raw in c.due():
        c.deliver(raw)
    assert [s["status"] for s in sent] == ["PICKED_UP"]
    assert c.advance(t, "EXCEPTION", "LOST")
    for raw in c.due():
        c.deliver(raw)
    assert sent[-1]["status"] == "EXCEPTION" and sent[-1]["exceptionCode"] == "LOST"
    assert not c.advance("nope")
