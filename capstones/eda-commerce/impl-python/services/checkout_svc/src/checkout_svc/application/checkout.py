"""checkout-svc use cases: carts, checkout submission, the catalog read model, order status.

``submit`` is the edge of the order saga: it validates against the local catalog read model,
freezes prices, mints the orderId, and writes the checkout row + CheckoutSubmitted outbox row in
one transaction (the caller wraps it with the Idempotency-Key store, ADR-0012).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from contracts_py.records import CheckoutSubmitted
from edacommon.envelope import Causation, OutgoingMessage
from edacommon.ids import new_id, rfc3339

from checkout_svc.application.ports import Cart, CartRepository, CatalogView, EventPublisher
from checkout_svc.domain.money import Money
from checkout_svc.domain.pricing import CartStatus, CheckoutRefused, Quote, check_can_add, price_lines, quote, validate_checkout


def _m(m: Money) -> dict[str, Any]:
    return {"amountMinor": m.amount_minor, "currency": m.currency}


@dataclass
class Checkout:
    carts: CartRepository
    catalog: CatalogView
    events: EventPublisher

    # ---------------------------------------------------------------------------------- carts
    def create_cart(self, customer_id: str, currency: str, now: datetime) -> Cart:
        cart = Cart(new_id(), customer_id, CartStatus.OPEN.value, currency, 1, ())
        self.carts.create(cart, now)
        return cart

    def get_cart(self, cart_id: str, customer_id: str, *, for_update: bool = False) -> Cart:
        cart = self.carts.get(cart_id, for_update=for_update)
        if cart is None or cart.customer_id != customer_id:
            raise CheckoutRefused("not-found", f"no cart {cart_id}")
        return cart

    def set_item(self, cart_id: str, customer_id: str, sku: str, quantity: int, if_match: int | None, now: datetime) -> Cart:
        cart = self.get_cart(cart_id, customer_id, for_update=True)
        self._check_version(cart, if_match)
        if cart.status != CartStatus.OPEN:
            raise CheckoutRefused("cart-not-open", "the cart was already checked out")
        check_can_add(self.catalog.entries([sku]).get(sku), sku, quantity)
        items = dict(cart.items)
        items[sku] = quantity
        updated = replace(cart, items=tuple(items.items()), version=cart.version + 1)
        self.carts.save(updated, now)
        return updated

    def remove_item(self, cart_id: str, customer_id: str, sku: str, now: datetime) -> Cart:
        cart = self.get_cart(cart_id, customer_id, for_update=True)
        if cart.status != CartStatus.OPEN:
            raise CheckoutRefused("cart-not-open", "the cart was already checked out")
        items = [(s, q) for s, q in cart.items if s != sku]
        updated = replace(cart, items=tuple(items), version=cart.version + 1)
        self.carts.save(updated, now)
        return updated

    @staticmethod
    def _check_version(cart: Cart, if_match: int | None) -> None:
        if if_match is not None and if_match != cart.version:
            raise CheckoutRefused("precondition-failed", f"cart is at version {cart.version}")

    def view(self, cart: Cart, now: datetime) -> dict[str, Any]:
        """Cart response, re-priced from the current read model (pricedAt = its freshness)."""
        entries = self.catalog.entries([s for s, _ in cart.items])
        lines, subtotal, priced_at = (
            price_lines(list(cart.items), entries, cart.currency, now) if cart.items else ((), Money.zero(cart.currency), now)
        )
        return {
            "cartId": cart.cart_id,
            "status": cart.status,
            "subtotal": _m(subtotal),
            "pricedAt": rfc3339(priced_at),
            "lines": [
                {
                    "sku": x.sku,
                    "productName": x.product_name,
                    "quantity": x.quantity,
                    "unitPrice": _m(x.unit_price),
                    "lineTotal": _m(x.line_total),
                    "availability": x.availability,
                }
                for x in lines
            ],
        }

    # ------------------------------------------------------------------------------- checkout
    def submit(
        self,
        *,
        customer_id: str,
        cart_id: str,
        shipping_address: dict[str, Any],
        contact_email: str,
        shipping_method: str,
        payment_token: str,
        expected_total: Money,
        now: datetime,
    ) -> dict[str, Any]:
        cart = self.get_cart(cart_id, customer_id, for_update=True)
        items = list(cart.items)
        entries = self.catalog.entries([s for s, _ in items])
        if cart.status != CartStatus.OPEN:
            raise CheckoutRefused("cart-not-open", "the cart was already checked out")
        if not items:
            raise CheckoutRefused("cart-empty", "the cart is empty")
        q = quote(items, entries, cart.currency, shipping_method, now)
        validate_checkout(cart.status, items, entries, q, expected_total)
        order_id, checkout_id = new_id(), new_id()  # checkout-svc mints the orderId (architecture §3)
        self.carts.save(replace(cart, status=CartStatus.CHECKED_OUT.value, version=cart.version + 1), now)
        self.carts.record_checkout(
            checkout_id=checkout_id, order_id=order_id, cart=cart, total_minor=q.total.amount_minor, now=now
        )
        self.events.publish(
            self._submitted(checkout_id, order_id, cart, q, shipping_address, contact_email, shipping_method, payment_token)
        )
        return {
            "checkoutId": checkout_id,
            "orderId": order_id,
            "status": "PENDING",
            "total": _m(q.total),
            "statusUrl": f"/orders/{order_id}",
        }

    @staticmethod
    def _submitted(
        checkout_id: str, order_id: str, cart: Cart, q: Quote, address: dict[str, Any], email: str, method: str, token: str
    ) -> OutgoingMessage:
        body = {
            "checkoutId": checkout_id,
            "orderId": order_id,
            "cartId": cart.cart_id,
            "customerId": cart.customer_id,
            "lines": [
                {
                    "lineId": new_id(),
                    "sku": x.sku,
                    "productName": x.product_name,
                    "quantity": x.quantity,
                    "unitPrice": _m(x.unit_price),
                    "lineTotal": _m(x.line_total),
                }
                for x in q.lines
            ],
            "subtotal": _m(q.subtotal),
            "shippingFee": _m(q.shipping_fee),
            "tax": _m(q.tax),
            "total": _m(q.total),
            "shippingAddress": {
                k: address.get(k)
                for k in ("recipientName", "line1", "line2", "city", "region", "postalCode", "countryCode", "phone")
            },
            "contactEmail": email,
            "shippingMethod": method,
            "paymentMethodToken": token,
            "priceSnapshotAt": q.priced_at,
        }
        # Started by an HTTP request: correlation = the new orderId, no causation (Envelope doc).
        return OutgoingMessage(
            topic=CheckoutSubmitted.TOPIC,
            record_type=CheckoutSubmitted.AVRO_NAME,
            key=order_id,
            body=body,
            aggregate_type="Checkout",
            aggregate_id=checkout_id,
            aggregate_version=1,
            causation=Causation(correlation_id=order_id),
        )
