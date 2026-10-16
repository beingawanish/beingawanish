"""Configuration: seat types, prices, hold length, refund tiers.

Every number the business can change lives here, in frozen dataclasses,
so the booking logic never contains a literal price or a literal timeout.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from enum import Enum

from .errors import InvalidConfigError


class SeatType(Enum):
    REGULAR = "regular"
    PREMIUM = "premium"
    RECLINER = "recliner"


@dataclass(frozen=True)
class RefundTier:
    """Cancel at least `min_hours_before_show` hours ahead, get `refund_percent` back."""

    min_hours_before_show: int
    refund_percent: int


@dataclass(frozen=True)
class BookingConfig:
    hold_seconds: int = 600
    max_seats_per_booking: int = 10
    currency: str = "INR"
    seat_prices: dict[SeatType, Decimal] = field(default_factory=lambda: {
        SeatType.REGULAR: Decimal("200.00"),
        SeatType.PREMIUM: Decimal("350.00"),
        SeatType.RECLINER: Decimal("600.00"),
    })
    # Most generous tier first. Anything later than the last tier refunds nothing.
    refund_tiers: tuple[RefundTier, ...] = (
        RefundTier(min_hours_before_show=24, refund_percent=100),
        RefundTier(min_hours_before_show=4, refund_percent=50),
    )

    def __post_init__(self) -> None:
        if self.hold_seconds <= 0:
            raise InvalidConfigError("hold_seconds must be positive")
        if self.max_seats_per_booking <= 0:
            raise InvalidConfigError("max_seats_per_booking must be positive")
        missing = [t.name for t in SeatType if t not in self.seat_prices]
        if missing:
            raise InvalidConfigError(f"no price for seat types: {missing}")
        if any(p < 0 for p in self.seat_prices.values()):
            raise InvalidConfigError("seat prices cannot be negative")
        hours = [t.min_hours_before_show for t in self.refund_tiers]
        if hours != sorted(hours, reverse=True) or len(set(hours)) != len(hours):
            raise InvalidConfigError("refund tiers must be strictly descending by hours")
        if any(not 0 <= t.refund_percent <= 100 for t in self.refund_tiers):
            raise InvalidConfigError("refund_percent must be within 0..100")

    @property
    def hold_duration(self) -> timedelta:
        return timedelta(seconds=self.hold_seconds)
