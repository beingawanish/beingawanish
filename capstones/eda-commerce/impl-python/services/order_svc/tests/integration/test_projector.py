"""order-history-projector: replay from offset 0 into an empty schema yields the same rows as
incremental processing (with duplicates and redeliveries); stale versions are dropped."""

from __future__ import annotations

import random
from typing import Any

import pytest
from edacommon.consumer import ConsumedRecord, MessageProcessor, Outcome
from edacommon.consumer.forwarder import Forwarder
from order_svc.adapters.projector.projection import build_registry
from order_svc.adapters.projector.schema import ddl
from sqlalchemy import text

from .conftest import Svc, drive_to_delivered

pytestmark = pytest.mark.integration


def records(svc: Svc) -> list[ConsumedRecord]:
    out = []
    for i, pub in enumerate(x for x in svc.all if x.topic.endswith(".events.v1")):
        data = svc.h.serde.serialize(pub.topic, pub.type, pub.value)
        out.append(
            ConsumedRecord(
                topic=pub.topic,
                partition=0,
                offset=i,
                key=(pub.key or "").encode(),
                value=data,
                headers=[(k, v.encode() if v else None) for k, v in pub.headers.items()],
            )
        )
    return out


def processor(svc: Svc, schema: str, group: str) -> MessageProcessor:
    return MessageProcessor(
        group=group,
        registry=build_registry(schema),
        db=svc.h.db,
        serde=svc.h.serde,
        forwarder=Forwarder(svc.h.producer, group),
        metrics=svc.h.metrics,
        clock=svc.h.clock,
        sleep=lambda s: None,
    )


def snapshot(svc: Svc, schema: str) -> Any:
    with svc.h.db.unit_of_work() as uow:
        s = uow.session
        return (
            s.execute(text(f"SELECT * FROM {schema}.order_summary ORDER BY order_id")).all(),
            s.execute(text(f"SELECT * FROM {schema}.order_line ORDER BY order_id, line_id")).all(),
            s.execute(text(f"SELECT * FROM {schema}.timeline ORDER BY order_id, event_id")).all(),
        )


def test_replay_equals_incremental_and_stale_versions_drop(svc: Svc) -> None:
    drive_to_delivered(svc, "0193a1c4-0000-7000-8000-00000000d001")
    drive_to_delivered(svc, "0193a1c4-0000-7000-8000-00000000d002")
    recs = records(svc)
    # incremental: one at a time, with redeliveries (the inbox dedupes)
    live = processor(svc, "order_history", "order-history-projector")
    for r in recs:
        assert live.process(r).outcome in (Outcome.SUCCESS, Outcome.IGNORED)
        if random.random() < 0.3:
            live.process(r)
    # rebuild: new schema, new group, from offset 0 (ADR-0010)
    with svc.h.db.unit_of_work() as uow:
        for stmt in ddl("order_history_v2"):
            uow.session.execute(text(stmt))
    rebuild = processor(svc, "order_history_v2", "order-history-projector-v2")
    for r in recs:
        rebuild.process(r)
    assert snapshot(svc, "order_history") == snapshot(svc, "order_history_v2")
    summary = snapshot(svc, "order_history")[0]
    assert {row.status for row in summary} == {"DELIVERED"}

    # A stale (older) order event re-published under a new eventId (e.g. a Debezium snapshot
    # re-read) must not move the status backwards.
    confirmed = next(p for p in svc.all if p.type.endswith("OrderConfirmed"))
    value = dict(confirmed.value)
    value["envelope"] = {**value["envelope"], "eventId": "0193a1c4-ffff-7000-8000-000000000001"}
    data = svc.h.serde.serialize(confirmed.topic, confirmed.type, value)
    stale = ConsumedRecord(
        topic=confirmed.topic,
        partition=0,
        offset=999,
        key=(confirmed.key or "").encode(),
        value=data,
        headers=[("ce_id", b"0193a1c4-ffff-7000-8000-000000000001"), ("ce_type", confirmed.type.encode())],
    )
    assert live.process(stale).outcome is Outcome.SUCCESS
    assert {row.status for row in snapshot(svc, "order_history")[0]} == {"DELIVERED"}
