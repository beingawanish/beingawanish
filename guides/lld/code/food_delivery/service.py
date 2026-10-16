"""The use-case layer: carts, checkout, the order lifecycle, and dispatch.

The service orchestrates. Prices come from the pipeline, partners from the
dispatcher, ETAs from the estimator, refunds from the policy, and the legal
moves from the transition table. What the service owns is the sequence,
and the one RLock that makes each sequence atomic.

Events are collected while the lock is held and published after it is
released, so a slow observer never blocks other orders.
"""
import logging
import threading
from datetime import datetime

from .cart import Cart
from .clock import Clock, SystemClock
from .config import FoodDeliveryConfig
from .dispatch import (
    Dispatcher,
    DispatchOutcome,
    DispatchResult,
    NearestPartnerStrategy,
)
from .errors import (
    CancellationNotAllowedError,
    EmptyCartError,
    IdempotencyKeyReusedError,
    ItemUnavailableError,
    OrderNotFoundError,
    PartnerMismatchError,
    PartnerNotFoundError,
    RestaurantClosedError,
    RestaurantNotFoundError,
)
from .eta import DistanceEtaEstimator, EtaEstimator
from .models import Bill, Location, Order, OrderLine, Restaurant
from .notifications import EventKind, Notifier, OrderEvent
from .pricing import DiscountRule, PricingPipeline
from .refunds import RefundPolicy, StandardRefundPolicy
from .repositories import (
    InMemoryOrders,
    InMemoryPartners,
    InMemoryRestaurants,
    OrderRepository,
    PartnerRepository,
    RestaurantRepository,
)
from .status import Actor, OrderStatus

log = logging.getLogger(__name__)

_DISPATCH_EVENTS = {
    DispatchResult.OFFERED: EventKind.PARTNER_OFFERED,
    DispatchResult.WAITING: EventKind.DISPATCH_WAITING,
    DispatchResult.FAILED: EventKind.DISPATCH_FAILED,
}


def _require_text(value: str, name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value.strip()


class FoodDeliveryService:
    def __init__(
        self,
        *,
        clock: Clock | None = None,
        config: FoodDeliveryConfig | None = None,
        restaurants: RestaurantRepository | None = None,
        partners: PartnerRepository | None = None,
        orders: OrderRepository | None = None,
        discounts: DiscountRule | None = None,
        pricing: PricingPipeline | None = None,
        dispatcher: Dispatcher | None = None,
        eta: EtaEstimator | None = None,
        refunds: RefundPolicy | None = None,
        notifier: Notifier | None = None,
    ):
        self._clock = clock or SystemClock()
        self._config = config or FoodDeliveryConfig()
        self._restaurants = restaurants or InMemoryRestaurants()
        self._partners = partners or InMemoryPartners()
        self._orders = orders or InMemoryOrders()
        self._pricing = pricing or PricingPipeline.standard(
            self._config.pricing, discounts)
        self._dispatcher = dispatcher or Dispatcher(
            self._partners,
            NearestPartnerStrategy(self._config.dispatch.max_pickup_radius_km),
            self._clock, self._config.dispatch)
        self._eta = eta or DistanceEtaEstimator(self._config.eta)
        self._refunds = refunds or StandardRefundPolicy(self._config.refunds)
        self._notifier = notifier or Notifier()
        self._lock = threading.RLock()          # guards _carts and every order change
        self._carts: dict[str, Cart] = {}

    # -- catalogue ------------------------------------------------------

    def set_item_available(self, restaurant_id: str, item_id: str,
                           available: bool) -> None:
        with self._lock:
            self._restaurant(restaurant_id).item(item_id).available = available

    def set_paused(self, restaurant_id: str, paused: bool) -> None:
        with self._lock:
            self._restaurant(restaurant_id).paused = paused

    # -- cart -----------------------------------------------------------

    def add_to_cart(self, customer_id: str, restaurant_id: str, item_id: str,
                    quantity: int = 1, *, replace: bool = False) -> dict[str, int]:
        customer_id = _require_text(customer_id, "customer_id")
        with self._lock:
            item = self._restaurant(restaurant_id).item(item_id)
            if not item.available:
                raise ItemUnavailableError(f"{item.name} is not available right now")
            cart = self._carts.setdefault(
                customer_id, Cart(customer_id, self._config.max_quantity_per_line))
            cart.add(restaurant_id, item_id, quantity, replace=replace)
            return cart.items()

    def remove_from_cart(self, customer_id: str, item_id: str,
                         quantity: int | None = None) -> dict[str, int]:
        with self._lock:
            cart = self._carts.get(customer_id)
            if cart is None:
                return {}
            cart.remove(item_id, quantity)
            return cart.items()

    def cart(self, customer_id: str) -> dict[str, int]:
        with self._lock:
            cart = self._carts.get(customer_id)
            return cart.items() if cart else {}

    # -- checkout -------------------------------------------------------

    def quote(self, customer_id: str, drop: Location,
              coupon_code: str | None = None) -> Bill:
        with self._lock:
            restaurant, lines = self._checkout_lines(customer_id)
        return self._pricing.price(
            lines, restaurant.location.distance_to(drop), coupon_code)

    def place_order(self, customer_id: str, drop: Location, idempotency_key: str,
                    coupon_code: str | None = None) -> Order:
        """Safe to retry: the same key returns the same order, charged once."""
        customer_id = _require_text(customer_id, "customer_id")
        key = _require_text(idempotency_key, "idempotency_key")
        code = coupon_code.strip().upper() if coupon_code else None
        with self._lock:
            existing = self._orders.find_by_key(customer_id, key)
            if existing is not None:
                if (existing.drop, existing.coupon_code) != (drop, code):
                    raise IdempotencyKeyReusedError(
                        f"key {key} was used for a different request")
                log.info("replay of key %s -> %s", key, existing.order_id)
                return existing
            restaurant, lines = self._checkout_lines(customer_id)
            bill = self._pricing.price(
                lines, restaurant.location.distance_to(drop), code)
            now = self._clock.now()
            order = Order(
                order_id=self._orders.next_id(), customer_id=customer_id,
                restaurant_id=restaurant.restaurant_id, lines=lines, bill=bill,
                drop=drop, coupon_code=code, idempotency_key=key, placed_at=now,
                eta=now + self._eta.estimate(restaurant, drop, None))
            self._orders.add(order)
            self._carts[customer_id].clear()
            log.info("placed %s for %s, total %s", order.order_id,
                     customer_id, bill.total)
            events = [self._event(order, EventKind.STATUS_CHANGED)]
        self._notifier.publish(events)
        return order

    # -- restaurant side ------------------------------------------------

    def accept(self, order_id: str) -> Order:
        """The restaurant takes the order; dispatch starts right away, so a
        partner rides over while the kitchen cooks."""
        with self._lock:
            order = self._order(order_id)
            events = [self._move(order, OrderStatus.ACCEPTED, Actor.RESTAURANT)]
            pickup = self._restaurant(order.restaurant_id).location
            outcome = self._dispatcher.start(order.order_id, pickup)
            events += self._handle_dispatch(outcome)
        self._notifier.publish(events)
        return order

    def reject(self, order_id: str) -> Order:
        return self._end(order_id, OrderStatus.REJECTED, Actor.RESTAURANT)

    def start_preparing(self, order_id: str) -> Order:
        return self._step(order_id, OrderStatus.PREPARING, Actor.RESTAURANT)

    def mark_ready(self, order_id: str) -> Order:
        return self._step(order_id, OrderStatus.READY, Actor.RESTAURANT)

    # -- partner side ---------------------------------------------------

    def partner_accept(self, order_id: str, partner_id: str) -> Order:
        with self._lock:
            order = self._order(order_id)
            self._dispatcher.accept(order_id, partner_id)
            partner = self._partners.get(partner_id)
            if partner is None:
                raise PartnerNotFoundError(f"no partner {partner_id}")
            order.partner_id = partner_id
            restaurant = self._restaurant(order.restaurant_id)
            order.eta = self._clock.now() + self._eta.estimate(
                restaurant, order.drop, partner.location)
            self._orders.save(order)
            events = [self._event(order, EventKind.PARTNER_ASSIGNED,
                                  f"{partner.name}, eta {order.eta:%H:%M}")]
        self._notifier.publish(events)
        return order

    def partner_decline(self, order_id: str, partner_id: str) -> Order:
        with self._lock:
            order = self._order(order_id)
            events = self._handle_dispatch(
                self._dispatcher.decline(order_id, partner_id))
        self._notifier.publish(events)
        return order

    def pick_up(self, order_id: str, partner_id: str) -> Order:
        with self._lock:
            order = self._order(order_id)
            self._check_partner(order, partner_id)
            event = self._move(order, OrderStatus.PICKED_UP, Actor.PARTNER)
        self._notifier.publish([event])
        return order

    def deliver(self, order_id: str, partner_id: str) -> Order:
        with self._lock:
            order = self._order(order_id)
            self._check_partner(order, partner_id)
            event = self._move(order, OrderStatus.DELIVERED, Actor.PARTNER)
            self._dispatcher.finish(order_id)
        self._notifier.publish([event])
        return order

    # -- cancellation and housekeeping -----------------------------------

    def cancel(self, order_id: str, actor: Actor = Actor.CUSTOMER) -> Order:
        return self._end(order_id, OrderStatus.CANCELLED, actor)

    def tick(self) -> list[DispatchOutcome]:
        """Call on a schedule: re-offers timed-out offers, and cancels orders
        nobody would deliver."""
        with self._lock:
            outcomes = self._dispatcher.expire_stale()
            events = []
            for outcome in outcomes:
                events += self._handle_dispatch(outcome)
        self._notifier.publish(events)
        return outcomes

    def eta(self, order_id: str) -> datetime:
        with self._lock:
            return self._order(order_id).eta

    def get_order(self, order_id: str) -> Order:
        with self._lock:
            return self._order(order_id)

    # -- helpers --------------------------------------------------------

    def _restaurant(self, restaurant_id: str) -> Restaurant:
        restaurant = self._restaurants.get(restaurant_id)
        if restaurant is None:
            raise RestaurantNotFoundError(f"no restaurant {restaurant_id}")
        return restaurant

    def _order(self, order_id: str) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"no order {order_id}")
        return order

    def _checkout_lines(self, customer_id: str) -> tuple[Restaurant, tuple[OrderLine, ...]]:
        """Re-validate the cart against the live menu. Caller holds the lock."""
        cart = self._carts.get(customer_id)
        if cart is None or cart.is_empty or cart.restaurant_id is None:
            raise EmptyCartError(f"cart for {customer_id} is empty")
        restaurant = self._restaurant(cart.restaurant_id)
        if not restaurant.is_open(self._clock.now()):
            raise RestaurantClosedError(f"{restaurant.name} is not taking orders")
        lines = []
        for item_id, quantity in cart.items().items():
            item = restaurant.item(item_id)
            if not item.available:
                raise ItemUnavailableError(f"{item.name} sold out; remove it to continue")
            lines.append(OrderLine(item.item_id, item.name, item.price, quantity))
        return restaurant, tuple(lines)

    def _check_partner(self, order: Order, partner_id: str) -> None:
        if order.partner_id is None or order.partner_id != partner_id:
            raise PartnerMismatchError(
                f"{order.order_id} is assigned to {order.partner_id}, not {partner_id}")

    def _event(self, order: Order, kind: EventKind, detail: str = "") -> OrderEvent:
        return OrderEvent(kind, order.order_id, order.customer_id, order.status,
                          self._clock.now(), detail)

    def _move(self, order: Order, target: OrderStatus, actor: Actor) -> OrderEvent:
        order.advance(target, self._clock.now(), actor)
        self._orders.save(order)
        log.info("%s -> %s by %s", order.order_id, target.name, actor.value)
        return self._event(order, EventKind.STATUS_CHANGED)

    def _step(self, order_id: str, target: OrderStatus, actor: Actor) -> Order:
        with self._lock:
            order = self._order(order_id)
            event = self._move(order, target, actor)
        self._notifier.publish([event])
        return order

    def _end(self, order_id: str, target: OrderStatus, actor: Actor) -> Order:
        with self._lock:
            order = self._order(order_id)
            events = self._end_locked(order, target, actor)
        self._notifier.publish(events)
        return order

    def _end_locked(self, order: Order, target: OrderStatus,
                    actor: Actor) -> list[OrderEvent]:
        if actor is Actor.CUSTOMER and not self._refunds.customer_may_cancel(order.status):
            raise CancellationNotAllowedError(
                f"{order.order_id} is {order.status.name}; too late to cancel")
        refund = self._refunds.refund_for(order, actor)
        event = self._move(order, target, actor)
        order.refund = refund
        self._dispatcher.finish(order.order_id)
        log.info("%s ended by %s, refund %s", order.order_id, actor.value, refund)
        return [event]

    def _handle_dispatch(self, outcome: DispatchOutcome) -> list[OrderEvent]:
        order = self._order(outcome.order_id)
        events = [self._event(order, _DISPATCH_EVENTS[outcome.result],
                              f"attempt {outcome.attempt} {outcome.partner_id or ''}".strip())]
        if outcome.result is DispatchResult.FAILED:
            events += self._end_locked(order, OrderStatus.CANCELLED, Actor.PLATFORM)
        return events
