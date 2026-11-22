"""Pure tests: fulfilment decisions, warehouse progress rules, inspection grouping, parcels, fake WMS."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fulfilment_svc.adapters.outbound.wms.fake.wms import FakeWms, FakeWmsConfig
from fulfilment_svc.application.ports import InspectionReport, WarehouseEvent
from fulfilment_svc.domain.model import (
    CancelDecision,
    DispatchDecision,
    Fulfilment,
    FulfilmentStatus,
    InspectionOutcome,
    InspectionResult,
    OrderLine,
    RequestDecision,
    ReturnLine,
    WarehouseStep,
    decide_cancel,
    decide_dispatch,
    decide_request,
    group_outcomes,
    plan_parcels,
    warehouse_step_applies,
)

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
LINES = (OrderLine("l1", "SKU-1001", "Shoe", 2),)


def f(status: FulfilmentStatus) -> Fulfilment:
    return Fulfilment("f1", "o1", status, LINES, {"recipientName": "x"}, "STANDARD", "o1")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, RequestDecision.CREATE_AND_SUBMIT),
        (FulfilmentStatus.REQUESTED, RequestDecision.RESUBMIT),
        (FulfilmentStatus.ACCEPTED, RequestDecision.ANSWER_ACCEPTED),
        (FulfilmentStatus.PICKED, RequestDecision.ANSWER_ACCEPTED),
        (FulfilmentStatus.PACKED, RequestDecision.ANSWER_ACCEPTED),
        (FulfilmentStatus.DISPATCHED, RequestDecision.ANSWER_ACCEPTED),
        (FulfilmentStatus.CANCELLED, RequestDecision.ANSWER_CANCELLED),
        (FulfilmentStatus.FAILED, RequestDecision.ANSWER_FAILED),
    ],
)
def test_request_decisions(status: FulfilmentStatus | None, expected: RequestDecision) -> None:
    assert decide_request(f(status) if status else None) is expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, CancelDecision.TOMBSTONE),
        (FulfilmentStatus.REQUESTED, CancelDecision.CANCEL),
        (FulfilmentStatus.PACKED, CancelDecision.CANCEL),
        (FulfilmentStatus.DISPATCHED, CancelDecision.REFUSE_DISPATCHED),
        (FulfilmentStatus.CANCELLED, CancelDecision.ANSWER_CANCELLED),
        (FulfilmentStatus.FAILED, CancelDecision.ANSWER_CANCELLED),
    ],
)
def test_cancel_decisions(status: FulfilmentStatus | None, expected: CancelDecision) -> None:
    assert decide_cancel(f(status) if status else None) is expected


def test_warehouse_progress_only_moves_forward_and_never_revives() -> None:
    assert warehouse_step_applies(f(FulfilmentStatus.REQUESTED), WarehouseStep.ACCEPTED)
    assert not warehouse_step_applies(f(FulfilmentStatus.ACCEPTED), WarehouseStep.ACCEPTED)  # replay
    assert warehouse_step_applies(f(FulfilmentStatus.PICKED), WarehouseStep.PACKED)
    assert not warehouse_step_applies(f(FulfilmentStatus.REQUESTED), WarehouseStep.PACKED)
    assert not warehouse_step_applies(f(FulfilmentStatus.CANCELLED), WarehouseStep.PICKED)
    assert not warehouse_step_applies(f(FulfilmentStatus.PACKED), WarehouseStep.FAILED)  # packed goods do not fail
    assert not warehouse_step_applies(None, WarehouseStep.ACCEPTED)


def test_dispatch_decisions() -> None:
    assert decide_dispatch(f(FulfilmentStatus.PACKED)) is DispatchDecision.DISPATCH
    assert decide_dispatch(f(FulfilmentStatus.DISPATCHED)) is DispatchDecision.ANSWER_DISPATCHED
    assert decide_dispatch(f(FulfilmentStatus.PICKED)) is DispatchDecision.NOT_PACKED
    assert decide_dispatch(f(FulfilmentStatus.CANCELLED)) is DispatchDecision.IGNORE_STOPPED


def test_group_outcomes_per_line_and_missing_units() -> None:
    line = ReturnLine("l1", "SKU-1001", 3)
    got = group_outcomes(line, [InspectionOutcome.RESTOCKABLE, InspectionOutcome.DAMAGED])
    assert got == [
        InspectionResult("l1", "SKU-1001", 1, InspectionOutcome.RESTOCKABLE),
        InspectionResult("l1", "SKU-1001", 1, InspectionOutcome.DAMAGED),
        InspectionResult("l1", "SKU-1001", 1, InspectionOutcome.MISSING),
    ]
    assert sum(r.quantity for r in group_outcomes(line, [InspectionOutcome.RESTOCKABLE] * 5)) == 3  # capped


def test_parcels_split_by_weight() -> None:
    heavy = (OrderLine("l1", "S", "x", 100),)
    parcels = plan_parcels(heavy, lambda i: f"p{i}")
    assert [p.weight_grams for p in parcels] == [20000, 20000, 5000]
    assert len({p.parcel_id for p in parcels}) == 3
    with pytest.raises(ValueError, match="positive"):
        OrderLine("l", "S", "x", 0)


def cfg(**kw: object) -> FakeWmsConfig:
    base = FakeWmsConfig(dropRequestRate=0, failRate=0, acceptDelayMs=1000, pickDelayMs=1000, packDelayMs=1000, manifestLines=50)
    return base.merged(dict(kw))


def drain(wms: FakeWms, now: datetime) -> list[WarehouseEvent | InspectionReport]:
    out = wms.poll(now)
    for e in out:
        wms.ack(e.event_id)
    return out


def test_fake_wms_progresses_on_the_clock_and_dedupes_pick_orders() -> None:
    wms = FakeWms(cfg(), seed=1)
    wms.submit_pick_order(fulfilment_id="f1", order_id="o1", lines=LINES, now=NOW)
    assert wms.poll(NOW) == []
    (acc,) = drain(wms, NOW + timedelta(seconds=1))
    assert isinstance(acc, WarehouseEvent) and acc.step is WarehouseStep.ACCEPTED and acc.warehouse_id
    wms.submit_pick_order(fulfilment_id="f1", order_id="o1", lines=LINES, now=NOW + timedelta(seconds=1))
    (again,) = drain(wms, NOW + timedelta(seconds=1))  # re-announces, with a fresh event id
    assert again.step is WarehouseStep.ACCEPTED and again.event_id != acc.event_id  # type: ignore[union-attr]
    steps = [e.step for e in drain(wms, NOW + timedelta(seconds=3)) if isinstance(e, WarehouseEvent)]
    assert steps == [WarehouseStep.PICKED, WarehouseStep.PACKED]
    assert wms.pick_orders("f1") == 1 and wms.submissions["f1"] == 2


def test_fake_wms_unacked_events_are_redelivered() -> None:
    wms = FakeWms(cfg(), seed=1)
    wms.submit_pick_order(fulfilment_id="f1", order_id="o1", lines=LINES, now=NOW)
    first = wms.poll(NOW + timedelta(seconds=1))
    assert wms.poll(NOW + timedelta(seconds=1)) == first


def test_fake_wms_drops_and_fails_on_purpose() -> None:
    wms = FakeWms(cfg(dropRequestRate=1.0), seed=1)
    wms.submit_pick_order(fulfilment_id="f1", order_id="o1", lines=LINES, now=NOW)
    assert drain(wms, NOW + timedelta(hours=1)) == [] and wms.dropped["f1"] == 1 and wms.pick_orders("f1") == 0
    wms.config = wms.config.merged({"dropRequestRate": 0.0, "failRate": 1.0})
    wms.submit_pick_order(fulfilment_id="f1", order_id="o1", lines=LINES, now=NOW)
    last = drain(wms, NOW + timedelta(hours=1))[-1]
    assert isinstance(last, WarehouseEvent) and last.step is WarehouseStep.FAILED and last.failure_reason == "STOCK_DAMAGED"


def test_fake_wms_cancel_stops_progress() -> None:
    wms = FakeWms(cfg(), seed=1)
    wms.submit_pick_order(fulfilment_id="f1", order_id="o1", lines=LINES, now=NOW)
    wms.cancel_pick_order("f1")
    assert drain(wms, NOW + timedelta(hours=1)) == []


def test_manifest_is_large_deterministic_json() -> None:
    wms = FakeWms(cfg(manifestLines=2000), seed=1)
    wms.submit_pick_order(fulfilment_id="f1", order_id="o1", lines=LINES, now=NOW)
    packed = [e for e in drain(wms, NOW + timedelta(hours=1)) if isinstance(e, WarehouseEvent) and e.step is WarehouseStep.PACKED]
    assert packed[0].manifest is not None
    doc = json.loads(packed[0].manifest)
    assert len(doc["scans"]) == 2000 and len(packed[0].manifest) > 256_000  # claim-check territory (ADR-0009)
    assert {s["sku"] for s in doc["scans"]} == {"SKU-1001"}


def test_inspection_outcomes_follow_the_damage_rate() -> None:
    wms = FakeWms(cfg(inspectionDamagedRate=1.0), seed=1)
    wms.inspect_return(return_id="r1", lines=(ReturnLine("l1", "SKU-1001", 2),), now=NOW)
    wms.inspect_return(return_id="r1", lines=(ReturnLine("l1", "SKU-1001", 2),), now=NOW)  # once per return
    (rep,) = drain(wms, NOW + timedelta(hours=1))
    assert isinstance(rep, InspectionReport)
    assert rep.results == (InspectionResult("l1", "SKU-1001", 2, InspectionOutcome.DAMAGED),)
