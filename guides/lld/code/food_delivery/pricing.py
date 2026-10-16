"""Pricing as a pipeline of steps, with discounts as a chain of rules.

    item total -> delivery fee -> discount chain -> tax -> Bill

Each step reads and writes one PricingContext. The order of steps is the
business rule ("tax is charged after discounts"), and it is visible in one
list instead of buried in one long function.

Discounts are a Chain of Responsibility. Every rule sees the context and
decides for itself whether it applies. A coupon rule acts only when the
code is its own, and only if no other coupon got there first.
"""
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import pairwise

from .config import PricingConfig
from .errors import CouponNotApplicableError, InvalidCouponError
from .models import Bill, OrderLine, to_money

ZERO = Decimal("0.00")


@dataclass
class PricingContext:
    lines: tuple[OrderLine, ...]
    distance_km: float
    coupon_code: str | None
    item_total: Decimal = ZERO
    delivery_fee: Decimal = ZERO
    discount: Decimal = ZERO
    tax: Decimal = ZERO
    coupon_applied: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def food_after_discount(self) -> Decimal:
        return self.item_total - self.discount


# -- discount rules: the chain ----------------------------------------

class DiscountRule(ABC):
    """One link. handle() applies this rule, then passes the context on."""

    def __init__(self) -> None:
        self._next: DiscountRule | None = None

    def then(self, rule: "DiscountRule") -> "DiscountRule":
        """Link rule after this one; returns rule, so calls chain left to right."""
        self._next = rule
        return rule

    def handle(self, ctx: PricingContext) -> None:
        self.apply(ctx)
        if self._next is not None:
            self._next.handle(ctx)

    @abstractmethod
    def apply(self, ctx: PricingContext) -> None:
        ...


class CouponRule(DiscountRule):
    """Template for coupon codes: match, check minimum spend, then discount."""

    def __init__(self, code: str, min_item_total: Decimal = ZERO):
        super().__init__()
        self.code = code.strip().upper()
        self.min_item_total = to_money(min_item_total)

    def apply(self, ctx: PricingContext) -> None:
        if ctx.coupon_applied or ctx.coupon_code != self.code:
            return
        if ctx.item_total < self.min_item_total:
            raise CouponNotApplicableError(
                f"{self.code} needs a food total of at least {self.min_item_total}")
        amount = min(self.discount_for(ctx), ctx.food_after_discount)
        ctx.discount += amount
        ctx.coupon_applied = True
        ctx.notes.append(f"{self.code}: -{amount}")

    @abstractmethod
    def discount_for(self, ctx: PricingContext) -> Decimal:
        ...


class PercentOffCoupon(CouponRule):
    def __init__(self, code: str, percent: Decimal, cap: Decimal,
                 min_item_total: Decimal = ZERO):
        super().__init__(code, min_item_total)
        if not Decimal(0) < percent <= Decimal(100):
            raise ValueError("percent must be in (0, 100]")
        self.percent = percent
        self.cap = to_money(cap)

    def discount_for(self, ctx: PricingContext) -> Decimal:
        return min(to_money(ctx.item_total * self.percent / 100), self.cap)


class FlatOffCoupon(CouponRule):
    def __init__(self, code: str, amount: Decimal, min_item_total: Decimal = ZERO):
        super().__init__(code, min_item_total)
        if amount <= 0:
            raise ValueError("amount must be positive")
        self.amount = to_money(amount)

    def discount_for(self, ctx: PricingContext) -> Decimal:
        return self.amount


class FreeDeliveryAbove(DiscountRule):
    """Automatic, no code needed. Put it after the coupons in the chain:
    the threshold is checked against food *after* the coupon."""

    def __init__(self, threshold: Decimal):
        super().__init__()
        self.threshold = to_money(threshold)

    def apply(self, ctx: PricingContext) -> None:
        if ctx.delivery_fee > 0 and ctx.food_after_discount >= self.threshold:
            ctx.notes.append(f"free delivery over {self.threshold}: -{ctx.delivery_fee}")
            ctx.delivery_fee = ZERO


def chain(*rules: DiscountRule) -> DiscountRule | None:
    """chain(a, b, c) links a -> b -> c and returns a (or None if empty)."""
    for current, following in pairwise(rules):
        current.then(following)
    return rules[0] if rules else None


# -- pipeline steps ----------------------------------------------------

class PricingStep(ABC):
    @abstractmethod
    def apply(self, ctx: PricingContext) -> None:
        ...


class ItemTotalStep(PricingStep):
    def apply(self, ctx: PricingContext) -> None:
        ctx.item_total = to_money(sum((line.line_total for line in ctx.lines), ZERO))


class DeliveryFeeStep(PricingStep):
    def __init__(self, config: PricingConfig):
        self._config = config

    def apply(self, ctx: PricingContext) -> None:
        distance = Decimal(str(round(ctx.distance_km, 2)))
        ctx.delivery_fee = to_money(
            self._config.base_delivery_fee + self._config.per_km_fee * distance)


class DiscountStep(PricingStep):
    def __init__(self, rules: DiscountRule | None):
        self._rules = rules

    def apply(self, ctx: PricingContext) -> None:
        if self._rules is not None:
            self._rules.handle(ctx)
        if ctx.coupon_code is not None and not ctx.coupon_applied:
            raise InvalidCouponError(f"unknown coupon {ctx.coupon_code}")


class TaxStep(PricingStep):
    def __init__(self, config: PricingConfig):
        self._config = config

    def apply(self, ctx: PricingContext) -> None:
        ctx.tax = to_money(ctx.food_after_discount * self._config.tax_rate)


class PricingPipeline:
    def __init__(self, steps: Sequence[PricingStep]):
        if not steps:
            raise ValueError("a pricing pipeline needs at least one step")
        self._steps = tuple(steps)

    @classmethod
    def standard(cls, config: PricingConfig,
                 discounts: DiscountRule | None = None) -> "PricingPipeline":
        return cls([ItemTotalStep(), DeliveryFeeStep(config),
                    DiscountStep(discounts), TaxStep(config)])

    def price(self, lines: tuple[OrderLine, ...], distance_km: float,
              coupon_code: str | None = None) -> Bill:
        code = coupon_code.strip().upper() if coupon_code else None
        ctx = PricingContext(lines=lines, distance_km=distance_km, coupon_code=code)
        for step in self._steps:
            step.apply(ctx)
        total = ctx.food_after_discount + ctx.delivery_fee + ctx.tax
        return Bill(item_total=ctx.item_total, discount=to_money(ctx.discount),
                    delivery_fee=ctx.delivery_fee, tax=ctx.tax,
                    total=to_money(total), notes=tuple(ctx.notes))
