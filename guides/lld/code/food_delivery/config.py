"""Configuration: every number the food-delivery domain depends on.

Money is Decimal, never float: a bill is added, discounted, taxed and
refunded, and float dust would show up on the customer's receipt.
Each group validates itself, so a bad deployment fails at startup.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from .status import OrderStatus


@dataclass(frozen=True)
class PricingConfig:
    tax_rate: Decimal = Decimal("0.05")            # charged on food after discounts
    base_delivery_fee: Decimal = Decimal("25.00")
    per_km_fee: Decimal = Decimal("8.00")

    def __post_init__(self) -> None:
        if not Decimal(0) <= self.tax_rate < Decimal(1):
            raise ValueError("tax_rate must be in [0, 1)")
        if self.base_delivery_fee < 0 or self.per_km_fee < 0:
            raise ValueError("delivery fees must not be negative")


@dataclass(frozen=True)
class DispatchConfig:
    offer_timeout: timedelta = timedelta(seconds=30)
    max_offer_attempts: int = 3
    max_pickup_radius_km: float = 5.0

    def __post_init__(self) -> None:
        if self.offer_timeout <= timedelta(0):
            raise ValueError("offer_timeout must be positive")
        if self.max_offer_attempts < 1:
            raise ValueError("max_offer_attempts must be at least 1")
        if self.max_pickup_radius_km <= 0:
            raise ValueError("max_pickup_radius_km must be positive")


@dataclass(frozen=True)
class EtaConfig:
    rider_speed_kmph: float = 20.0
    buffer_minutes: int = 5

    def __post_init__(self) -> None:
        if self.rider_speed_kmph <= 0:
            raise ValueError("rider_speed_kmph must be positive")
        if self.buffer_minutes < 0:
            raise ValueError("buffer_minutes must not be negative")


@dataclass(frozen=True)
class RefundConfig:
    """Fraction of the bill a customer gets back when *they* cancel.

    A status missing from the map means the customer can no longer cancel.
    Restaurant rejections and platform cancellations always refund in full;
    that rule lives in the refund policy, not here.
    """
    customer_refund_fraction: dict[OrderStatus, Decimal] = field(
        default_factory=lambda: {
            OrderStatus.PLACED: Decimal(1),
            OrderStatus.ACCEPTED: Decimal(1),
            OrderStatus.PREPARING: Decimal("0.5"),
        })

    def __post_init__(self) -> None:
        for status, fraction in self.customer_refund_fraction.items():
            if not Decimal(0) <= fraction <= Decimal(1):
                raise ValueError(f"refund fraction for {status.name} must be in [0, 1]")


@dataclass(frozen=True)
class FoodDeliveryConfig:
    pricing: PricingConfig = field(default_factory=PricingConfig)
    dispatch: DispatchConfig = field(default_factory=DispatchConfig)
    eta: EtaConfig = field(default_factory=EtaConfig)
    refunds: RefundConfig = field(default_factory=RefundConfig)
    max_quantity_per_line: int = 20

    def __post_init__(self) -> None:
        if self.max_quantity_per_line < 1:
            raise ValueError("max_quantity_per_line must be at least 1")
