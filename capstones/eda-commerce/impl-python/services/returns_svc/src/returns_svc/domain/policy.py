"""Return policy: eligibility and the refund rule (architecture §6.2). Pure: no I/O, no clock.

Refund rule (in the returns domain, never in payment):

* RESTOCKABLE units: full unit price.
* DAMAGED units: full unit price if the customer's reason is merchant fault (DAMAGED, WRONG_ITEM,
  NOT_AS_DESCRIBED); zero otherwise.
* MISSING units (and outcomes this build does not know, decoded as UNKNOWN): zero.
* Shipping fee: only for merchant-fault reasons, and only on the first return of the order.

Only RESTOCKABLE units go back to stock. Several returns per order are allowed; the eligibility view
tracks the quantity left per line.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

MERCHANT_FAULT = frozenset({"DAMAGED", "WRONG_ITEM", "NOT_AS_DESCRIBED"})


@dataclass(frozen=True, slots=True)
class OrderLine:
    line_id: str
    sku: str
    product_name: str
    quantity: int
    unit_price_minor: int
    line_total_minor: int


@dataclass(frozen=True, slots=True)
class OrderView:
    """returns-svc's own projection of order events (ADR-0010): enough to answer eligibility at once."""

    order_id: str
    customer_id: str
    currency: str
    total_minor: int
    lines: tuple[OrderLine, ...]
    shipping_fee_minor: int = 0
    ship_to: dict[str, Any] | None = None
    payment_id: str | None = None
    warehouse_id: str | None = None
    delivered_at: datetime | None = None
    cancelled: bool = False
    shipping_fee_return_id: str | None = None

    def window_ends_at(self, window: timedelta) -> datetime | None:
        return self.delivered_at + window if self.delivered_at else None


@dataclass(frozen=True, slots=True)
class ReturnLine:
    line_id: str
    sku: str
    quantity: int
    unit_price_minor: int


class NotEligible(Exception):
    def __init__(self, problem_type: str, detail: str) -> None:
        super().__init__(detail)
        self.problem_type = problem_type
        self.detail = detail


def shipping_fee_of(total_minor: int, lines: tuple[OrderLine, ...]) -> int:
    """Prices are VAT-inclusive, so the order total is the line totals plus the shipping fee."""
    return max(total_minor - sum(x.line_total_minor for x in lines), 0)


def returnable(view: OrderView, already: dict[str, int]) -> dict[str, int]:
    return {x.line_id: max(x.quantity - already.get(x.line_id, 0), 0) for x in view.lines}


def check_eligibility(
    view: OrderView, requested: list[tuple[str, int]], already: dict[str, int], now: datetime, window: timedelta
) -> tuple[ReturnLine, ...]:
    """Raise :class:`NotEligible` (-> 422 with a problem type) or return the lines to return."""
    if view.cancelled or view.delivered_at is None:
        raise NotEligible("order-not-delivered", f"order {view.order_id} has not been delivered")
    ends = view.window_ends_at(window)
    assert ends is not None
    if now > ends:
        raise NotEligible("return-window-closed", f"the return window closed at {ends.isoformat()}")
    by_id = {x.line_id: x for x in view.lines}
    wanted: dict[str, int] = {}
    for line_id, q in requested:
        if line_id not in by_id:
            raise NotEligible("unknown-order-line", f"order {view.order_id} has no line {line_id}")
        if q <= 0:
            raise NotEligible("validation-error", "quantity must be at least 1")
        wanted[line_id] = wanted.get(line_id, 0) + q
    left = returnable(view, already)
    for line_id, q in wanted.items():
        if q > left[line_id]:
            raise NotEligible("return-quantity-exceeded", f"line {line_id}: {q} requested, {left[line_id]} left to return")
    return tuple(ReturnLine(i, by_id[i].sku, q, by_id[i].unit_price_minor) for i, q in wanted.items())


def value_minor(lines: tuple[ReturnLine, ...]) -> int:
    return sum(x.unit_price_minor * x.quantity for x in lines)


def refundable_shipping_fee(view: OrderView, reason: str, return_id: str) -> int:
    """Merchant fault and the first return of the order (or this one, when it already claimed it)."""
    if reason not in MERCHANT_FAULT:
        return 0
    if view.shipping_fee_return_id not in (None, return_id):
        return 0
    return view.shipping_fee_minor


@dataclass(frozen=True, slots=True)
class Inspected:
    line_id: str
    sku: str
    quantity: int
    outcome: str  # RESTOCKABLE | DAMAGED | MISSING | UNKNOWN


@dataclass(frozen=True, slots=True)
class Settlement:
    refund_minor: int
    restock: tuple[tuple[str, int], ...]  # (sku, quantity), RESTOCKABLE units only
    full: bool  # every returned unit refunded in full -> REFUNDED, else PARTIALLY_REFUNDED


def settle(lines: tuple[ReturnLine, ...], results: tuple[Inspected, ...], reason: str, shipping_fee_minor: int) -> Settlement:
    by_id = {x.line_id: x for x in lines}
    seen: dict[str, int] = {}
    refund = 0
    refunded_units = 0
    restock: dict[str, int] = {}
    for r in results:
        line = by_id.get(r.line_id)
        if line is None:
            continue  # the warehouse reported something we did not ask to return
        q = min(r.quantity, line.quantity - seen.get(r.line_id, 0))
        if q <= 0:
            continue
        seen[r.line_id] = seen.get(r.line_id, 0) + q
        if r.outcome == "RESTOCKABLE":
            refund += q * line.unit_price_minor
            refunded_units += q
            restock[line.sku] = restock.get(line.sku, 0) + q
        elif r.outcome == "DAMAGED" and reason in MERCHANT_FAULT:
            refund += q * line.unit_price_minor
            refunded_units += q
    # Units the warehouse did not report are MISSING: no refund.
    total_units = sum(x.quantity for x in lines)
    if refund > 0:
        refund += shipping_fee_minor
    return Settlement(refund, tuple(sorted(restock.items())), refunded_units == total_units and total_units > 0)
