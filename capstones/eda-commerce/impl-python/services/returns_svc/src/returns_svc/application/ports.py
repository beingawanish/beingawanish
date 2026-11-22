"""Ports of returns-svc's application layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from returns_svc.domain.policy import OrderLine, OrderView


@dataclass(frozen=True, slots=True)
class StoredLine:
    line_id: str
    sku: str
    quantity: int
    unit_price_minor: int
    inspection: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ReturnRecord:
    """The return's read side (``return_request`` + ``return_line``), kept in step with the saga row."""

    return_id: str
    order_id: str
    customer_id: str
    reason: str
    comment: str | None
    status: str
    currency: str
    requested_at: datetime
    lines: tuple[StoredLine, ...]
    rma_number: str | None = None
    refund_minor: int | None = None
    refund_id: str | None = None
    label: dict[str, Any] | None = None
    parcel_due_by: datetime | None = None
    counts_against_order: bool = True


class ReturnsRepository(Protocol):
    # eligibility view (projection of order events)
    def view(self, order_id: str, *, for_update: bool = False) -> OrderView | None: ...

    def placed(
        self,
        *,
        order_id: str,
        customer_id: str,
        currency: str,
        total_minor: int,
        shipping_fee_minor: int,
        lines: tuple[OrderLine, ...],
        ship_to: dict[str, Any],
        now: datetime,
    ) -> None: ...

    def set_view_fact(self, order_id: str, now: datetime, **facts: Any) -> bool:
        """Set facts (payment_id, warehouse_id, delivered_at, cancelled). False: OrderPlaced not seen yet."""
        ...

    def claim_shipping_fee(self, order_id: str, return_id: str) -> None: ...

    # returns
    def returned_quantities(self, order_id: str) -> dict[str, int]: ...

    def insert(self, r: ReturnRecord, now: datetime) -> None: ...

    def update(self, r: ReturnRecord, now: datetime) -> None: ...

    def get(self, return_id: str) -> ReturnRecord | None: ...

    def for_order(self, order_id: str) -> list[ReturnRecord]: ...

    def return_id_for_refund(self, refund_id: str) -> str | None: ...

    def next_rma(self, year: int) -> int:
        """Gapless: locks the year's counter row in the current transaction (guide §6.2)."""
        ...


class LabelLinks(Protocol):
    def presign(self, claim_check: dict[str, Any], ttl_s: int) -> str: ...
