"""Ports of order-svc's application layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from order_svc.domain.invoice import Invoice


@dataclass(frozen=True, slots=True)
class OrderRecord:
    """The order write model (``orders`` + ``order_line``)."""

    order_id: str
    customer_id: str
    status: str
    total_minor: int
    currency: str
    placed_at: datetime
    version: int
    contact_email: str
    ship_to: dict[str, Any]
    shipping_method: str
    lines: tuple[dict[str, Any], ...]  # Avro LineItem shape


class OrderRepository(Protocol):
    def create(self, order: OrderRecord) -> None: ...

    def get(self, order_id: str) -> OrderRecord | None: ...

    def set_status(self, order_id: str, status: str, version: int, now: datetime) -> None: ...


@dataclass(frozen=True, slots=True)
class StoredInvoice:
    invoice_id: str
    order_id: str
    number: str
    document: dict[str, Any]  # ClaimCheck (Avro shape)
    issued_at: datetime


class InvoiceRepository(Protocol):
    def next_number(self, year: int) -> int:
        """Gapless: locks the year's counter row in the current transaction (guide §6.2)."""
        ...

    def save(self, inv: StoredInvoice, total_minor: int, currency: str) -> None: ...

    def for_order(self, order_id: str) -> StoredInvoice | None: ...


class InvoiceRenderer(Protocol):
    def render(self, invoice: Invoice) -> bytes: ...


class DocumentStore(Protocol):
    def put(self, bucket: str, key: str, data: bytes, content_type: str) -> dict[str, Any]:
        """Upload and return the ClaimCheck in Avro shape."""
        ...

    def presign(self, claim_check: dict[str, Any], ttl_s: int) -> str: ...
