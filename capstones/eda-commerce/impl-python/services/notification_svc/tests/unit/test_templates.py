"""Pure tests: templates, dedupe keys, money formatting."""

from __future__ import annotations

import pytest
from notification_svc.domain.templates import TEMPLATES, Notice, money, render


def test_dedupe_key_is_template_plus_business_id() -> None:
    assert Notice("invoice.v1", "inv-1", "o-1").dedupe_key == "invoice.v1:inv-1"


def test_money_formats_minor_units_without_floats() -> None:
    assert money(12999, "EUR") == "129.99 EUR"
    assert money(5, "EUR") == "0.05 EUR"
    assert money(-150, "EUR") == "-1.50 EUR"


def test_every_template_renders_with_missing_facts_tolerated() -> None:
    for t in TEMPLATES:
        r = render(Notice(t, "b", "o-1"), "Jane")
        assert r.subject and r.text.startswith("Hello Jane,")
    assert render(Notice("order-confirmed.v1", "o-1", "o-1"), None).text.startswith("Hello,")


def test_render_fills_facts() -> None:
    r = render(Notice("invoice.v1", "inv-1", "o-1", {"invoiceNumber": "INV-2026-000001", "total": "259.98 EUR"}), None)
    assert r.subject == "Your invoice INV-2026-000001" and "259.98 EUR" in r.text and "o-1" in r.text


def test_unknown_template_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown template"):
        render(Notice("nope.v1", "b", "o"), None)
