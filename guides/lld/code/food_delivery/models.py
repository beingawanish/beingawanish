"""Domain models: places, menus, partners, bills and orders.

Each model validates its own fields, so no half-built object ever exists.
Order.advance() is the only way an order's status changes, and it obeys the
transition table in status.py.
"""
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, tzinfo
from decimal import ROUND_HALF_UP, Decimal

from .errors import InvalidTransitionError, MenuItemNotFoundError
from .status import Actor, OrderStatus, can_transition

CENT = Decimal("0.01")


def to_money(value: Decimal | int | str) -> Decimal:
    """Round to cents, half-up, the way a receipt does."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _require_text(value: str, name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{name} must not be blank")


@dataclass(frozen=True)
class Location:
    """A point on a flat city grid, in kilometres. Good enough for an
    interview; a real system would call a routing service."""
    x_km: float
    y_km: float

    def distance_to(self, other: "Location") -> float:
        return math.hypot(self.x_km - other.x_km, self.y_km - other.y_km)


@dataclass
class MenuItem:
    item_id: str
    name: str
    price: Decimal
    available: bool = True

    def __post_init__(self) -> None:
        _require_text(self.item_id, "item_id")
        _require_text(self.name, "name")
        if self.price <= 0:
            raise ValueError(f"price of {self.item_id} must be positive")
        self.price = to_money(self.price)


@dataclass
class Restaurant:
    restaurant_id: str
    name: str
    location: Location
    opens_at: time
    closes_at: time
    prep_minutes: int
    menu: dict[str, MenuItem] = field(default_factory=dict)
    paused: bool = False
    tz: tzinfo = UTC                    # opening hours are local to the restaurant

    def __post_init__(self) -> None:
        _require_text(self.restaurant_id, "restaurant_id")
        _require_text(self.name, "name")
        if self.closes_at <= self.opens_at:
            raise ValueError("closes_at must be after opens_at")
        if self.prep_minutes < 0:
            raise ValueError("prep_minutes must not be negative")

    def is_open(self, at: datetime) -> bool:
        """Half-open hours, [opens_at, closes_at): at 23:00 sharp it is shut."""
        local = at.astimezone(self.tz).time()
        return not self.paused and self.opens_at <= local < self.closes_at

    def item(self, item_id: str) -> MenuItem:
        try:
            return self.menu[item_id]
        except KeyError:
            raise MenuItemNotFoundError(
                f"{self.restaurant_id} has no item {item_id}") from None


@dataclass
class DeliveryPartner:
    partner_id: str
    name: str
    location: Location
    available: bool = True

    def __post_init__(self) -> None:
        _require_text(self.partner_id, "partner_id")
        _require_text(self.name, "name")


@dataclass(frozen=True)
class OrderLine:
    """A priced snapshot of one cart entry, frozen at checkout."""
    item_id: str
    name: str
    unit_price: Decimal
    quantity: int

    @property
    def line_total(self) -> Decimal:
        return to_money(self.unit_price * self.quantity)


@dataclass(frozen=True)
class Bill:
    item_total: Decimal
    discount: Decimal
    delivery_fee: Decimal
    tax: Decimal
    total: Decimal
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class StatusChange:
    status: OrderStatus
    at: datetime
    actor: Actor


@dataclass
class Order:
    order_id: str
    customer_id: str
    restaurant_id: str
    lines: tuple[OrderLine, ...]
    bill: Bill
    drop: Location
    coupon_code: str | None
    idempotency_key: str
    placed_at: datetime
    eta: datetime
    status: OrderStatus = OrderStatus.PLACED
    partner_id: str | None = None
    refund: Decimal = Decimal("0.00")
    history: list[StatusChange] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.history:
            self.history.append(
                StatusChange(OrderStatus.PLACED, self.placed_at, Actor.CUSTOMER))

    def advance(self, target: OrderStatus, at: datetime, actor: Actor) -> None:
        if not can_transition(self.status, target):
            raise InvalidTransitionError(
                f"order {self.order_id}: {self.status.name} -> {target.name} "
                f"is not allowed")
        self.status = target
        self.history.append(StatusChange(target, at, actor))
