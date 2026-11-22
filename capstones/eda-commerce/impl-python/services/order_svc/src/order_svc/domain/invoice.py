"""Invoice numbering and content (guide §6.2: gapless per year). Pure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from order_svc.domain.money import Money


def invoice_number(year: int, seq: int) -> str:
    """``INV-2026-000123`` (guide §6.1)."""
    return f"INV-{year}-{seq:06d}"


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    sku: str
    product_name: str
    quantity: int
    unit_price: Money
    line_total: Money


@dataclass(frozen=True, slots=True)
class Invoice:
    invoice_id: str
    number: str
    order_id: str
    customer_id: str
    issued_at: datetime
    lines: tuple[InvoiceLine, ...]
    total: Money
    ship_to: tuple[str, ...]  # rendered address lines (personal data; only on the document)
