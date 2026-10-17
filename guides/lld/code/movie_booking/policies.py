"""Pricing and refund policies: the two rules the business changes most often.

Both are Strategies. A new formula (surge pricing, a stricter refund window)
is a new class handed to the service, never an edit to the service.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .config import BookingConfig
from .models import Booking, Seat, Show

CENT = Decimal("0.01")
ONE_HOUR = timedelta(hours=1)


class PricingStrategy(ABC):
    @abstractmethod
    def price(self, show: Show, seat: Seat) -> Decimal:
        """Price of one seat for one show."""


class SeatTypePricing(PricingStrategy):
    """Flat price per seat type, straight from the config."""

    def __init__(self, config: BookingConfig) -> None:
        self._config = config

    def price(self, show: Show, seat: Seat) -> Decimal:
        return self._config.seat_prices[seat.seat_type]


class RefundPolicy(ABC):
    @abstractmethod
    def refund_for(self, booking: Booking, show: Show, now: datetime) -> Decimal:
        """How much of booking.amount goes back if cancelled at `now`."""


class TieredRefundPolicy(RefundPolicy):
    """Walks the config's tiers, most generous first; the first one that fits wins."""

    def __init__(self, config: BookingConfig) -> None:
        self._tiers = config.refund_tiers

    def refund_for(self, booking: Booking, show: Show, now: datetime) -> Decimal:
        hours_before = (show.starts_at - now) / ONE_HOUR
        for tier in self._tiers:
            if hours_before >= tier.min_hours_before_show:
                share = booking.amount * tier.refund_percent / Decimal(100)
                return share.quantize(CENT, rounding=ROUND_HALF_UP)
        return Decimal("0.00")
