"""Pure domain tests: reservation decisions and stock rules (ADR-0016)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from inventory_svc.domain.model import (
    CommitDecision,
    ReleaseDecision,
    Reservation,
    ReservationStatus,
    StockLevel,
    StockLine,
    availability,
    decide_commit,
    decide_release,
    hold_until,
    merge_lines,
)

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)


def res(status: ReservationStatus, expires: datetime | None = NOW + timedelta(minutes=15)) -> Reservation:
    return Reservation("r1", "o1", status, (StockLine("SKU-1", 1),), expires)


def test_merge_lines_sums_and_sorts() -> None:
    assert merge_lines([StockLine("B", 1), StockLine("A", 2), StockLine("B", 3)]) == (StockLine("A", 2), StockLine("B", 4))


def test_quantity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        StockLine("A", 0)


def test_ttl_is_capped_by_service_setting() -> None:
    assert hold_until(NOW, 900, timedelta(seconds=900)) == NOW + timedelta(seconds=900)
    assert hold_until(NOW, 900, timedelta(seconds=60)) == NOW + timedelta(seconds=60)  # drill: RESERVATION_TTL=60s
    assert hold_until(NOW, 30, timedelta(seconds=900)) == NOW + timedelta(seconds=30)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ReservationStatus.COMMITTED, CommitDecision.ANSWER_COMMITTED),
        (ReservationStatus.EXPIRED, CommitDecision.ANSWER_EXPIRED),
        (ReservationStatus.RELEASED, CommitDecision.ANSWER_RELEASED),
        (ReservationStatus.REJECTED, CommitDecision.ANSWER_REJECTED),
    ],
)
def test_commit_resends_answer_with_original_outcome(status: ReservationStatus, expected: CommitDecision) -> None:
    assert decide_commit(res(status), NOW) is expected


def test_commit_held_valid_vs_expired() -> None:
    assert decide_commit(res(ReservationStatus.HELD), NOW) is CommitDecision.COMMIT
    late = NOW + timedelta(minutes=16)
    assert decide_commit(res(ReservationStatus.HELD), late) is CommitDecision.EXPIRE_THEN_ANSWER_EXPIRED
    assert decide_commit(None, NOW) is CommitDecision.UNKNOWN


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ReservationStatus.HELD, ReleaseDecision.RELEASE_HELD),
        (ReservationStatus.COMMITTED, ReleaseDecision.RETURN_ALLOCATED),
        (ReservationStatus.RELEASED, ReleaseDecision.ANSWER_RELEASED),
        (ReservationStatus.EXPIRED, ReleaseDecision.ANSWER_RELEASED),
        (ReservationStatus.REJECTED, ReleaseDecision.ANSWER_RELEASED),
    ],
)
def test_release_is_idempotent_compensation(status: ReservationStatus, expected: ReleaseDecision) -> None:
    assert decide_release(res(status)) is expected


def test_release_of_unknown_reservation_leaves_a_tombstone() -> None:
    assert decide_release(None) is ReleaseDecision.TOMBSTONE


def test_availability_bands() -> None:
    assert availability(None) == "UNKNOWN"
    assert availability(StockLevel("A", 3, 3, 1)) == "OUT_OF_STOCK"
    assert availability(StockLevel("A", 8, 4, 1)) == "LOW_STOCK"
    assert availability(StockLevel("A", 50, 0, 1)) == "IN_STOCK"
    assert StockLevel("A", 1, 3, 1).available == 0, "available never negative"
