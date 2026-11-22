"""Pure tests: eligibility (not delivered, window closed, over-quantity), refund rule, shipping fee."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from returns_svc.domain.policy import (
    Inspected,
    NotEligible,
    OrderLine,
    OrderView,
    ReturnLine,
    check_eligibility,
    refundable_shipping_fee,
    returnable,
    settle,
    shipping_fee_of,
)

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
W = timedelta(days=30)
LINES = (OrderLine("l-1", "SKU-1001", "Shoe", 2, 12999, 25998), OrderLine("l-2", "SKU-1002", "Sock", 1, 999, 999))


def view(**kw: object) -> OrderView:
    base = {
        "order_id": "o",
        "customer_id": "c",
        "currency": "EUR",
        "total_minor": 27496,
        "lines": LINES,
        "shipping_fee_minor": 499,
        "delivered_at": NOW - timedelta(days=5),
    }
    base.update(kw)
    return OrderView(**base)  # type: ignore[arg-type]


def problem(fn: object) -> str:
    with pytest.raises(NotEligible) as e:
        fn()  # type: ignore[operator]
    return e.value.problem_type


def test_eligibility_rules() -> None:
    assert check_eligibility(view(), [("l-1", 2)], {}, NOW, W) == (ReturnLine("l-1", "SKU-1001", 2, 12999),)
    assert problem(lambda: check_eligibility(view(delivered_at=None), [("l-1", 1)], {}, NOW, W)) == "order-not-delivered"
    assert problem(lambda: check_eligibility(view(cancelled=True), [("l-1", 1)], {}, NOW, W)) == "order-not-delivered"
    assert problem(lambda: check_eligibility(view(), [("l-1", 1)], {}, NOW + timedelta(days=26), W)) == "return-window-closed"
    assert check_eligibility(view(), [("l-1", 1)], {}, NOW + timedelta(days=25), W)  # last day still open
    assert problem(lambda: check_eligibility(view(), [("l-1", 1), ("l-1", 1)], {"l-1": 1}, NOW, W)) == "return-quantity-exceeded"
    assert problem(lambda: check_eligibility(view(), [("l-9", 1)], {}, NOW, W)) == "unknown-order-line"
    assert returnable(view(), {"l-1": 1}) == {"l-1": 1, "l-2": 1}


def test_shipping_fee_derivation_and_rule() -> None:
    assert shipping_fee_of(27496, LINES) == 499
    assert shipping_fee_of(26997, LINES) == 0
    assert refundable_shipping_fee(view(), "WRONG_ITEM", "r1") == 499
    assert refundable_shipping_fee(view(), "CHANGED_MIND", "r1") == 0
    assert refundable_shipping_fee(view(shipping_fee_return_id="r0"), "DAMAGED", "r1") == 0, "first return only"


def test_refund_rule() -> None:
    lines = (ReturnLine("l-1", "SKU-1001", 2, 12999),)
    mixed = (Inspected("l-1", "SKU-1001", 1, "RESTOCKABLE"), Inspected("l-1", "SKU-1001", 1, "DAMAGED"))
    s = settle(lines, mixed, "CHANGED_MIND", 0)
    assert (s.refund_minor, s.restock, s.full) == (12999, (("SKU-1001", 1),), False)
    s = settle(lines, mixed, "DAMAGED", 499)
    assert (s.refund_minor, s.restock, s.full) == (25998 + 499, (("SKU-1001", 1),), True)
    s = settle(lines, (Inspected("l-1", "SKU-1001", 2, "MISSING"),), "DAMAGED", 499)
    assert s.refund_minor == 0 and s.restock == (), "no refund, so no fee either"
    s = settle(lines, (Inspected("l-1", "SKU-1001", 1, "RESTOCKABLE"),), "CHANGED_MIND", 0)
    assert s.refund_minor == 12999 and not s.full, "unreported units are missing"
    s = settle(lines, (Inspected("l-1", "SKU-1001", 5, "RESTOCKABLE"), Inspected("l-9", "X", 1, "RESTOCKABLE")), "OTHER", 0)
    assert s.refund_minor == 25998 and s.restock == (("SKU-1001", 2),), "capped, foreign lines ignored"
    assert settle(lines, (Inspected("l-1", "SKU-1001", 2, "UNKNOWN"),), "DAMAGED", 0).refund_minor == 0
