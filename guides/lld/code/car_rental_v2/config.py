"""Version 2 configuration: every number the follow-ups introduce.

Version 1's RentalConfig is untouched. V2Config sits beside it and holds only
what the follow-ups added. Each section validates itself in __post_init__,
so a bad number fails at startup, not halfway through a quote.
"""
from dataclasses import dataclass, field

from car_rental import VehicleCategory

from .models import DamageKind, LoyaltyTier


def _fraction(value: float, name: str) -> None:
    if not 0.0 <= value < 1.0:
        raise ValueError(f"{name} must be in [0, 1), got {value}")


@dataclass(frozen=True)
class PricingRulesConfig:
    weekend_days: frozenset[int] = frozenset({5, 6})   # date.weekday(): Sat, Sun
    weekend_multiplier: float = 1.2
    # (utilisation at least, multiplier), highest threshold first.
    surge_tiers: tuple[tuple[float, float], ...] = ((0.8, 1.25), (0.5, 1.10))
    long_rental_min_days: int = 7
    long_rental_discount: float = 0.10
    loyalty_discounts: dict[LoyaltyTier, float] = field(default_factory=lambda: {
        LoyaltyTier.NONE: 0.0,
        LoyaltyTier.SILVER: 0.05,
        LoyaltyTier.GOLD: 0.10,
    })

    def __post_init__(self) -> None:
        if self.weekend_multiplier < 1.0:
            raise ValueError("weekend_multiplier must be >= 1")
        thresholds = [t for t, _ in self.surge_tiers]
        if thresholds != sorted(thresholds, reverse=True):
            raise ValueError("surge_tiers must be ordered highest threshold first")
        for threshold, multiplier in self.surge_tiers:
            if not 0.0 <= threshold <= 1.0 or multiplier < 1.0:
                raise ValueError(f"bad surge tier ({threshold}, {multiplier})")
        if self.long_rental_min_days < 1:
            raise ValueError("long_rental_min_days must be >= 1")
        _fraction(self.long_rental_discount, "long_rental_discount")
        for tier in LoyaltyTier:
            _fraction(self.loyalty_discounts.get(tier, 0.0), f"loyalty {tier.name}")


@dataclass(frozen=True)
class EvConfig:
    min_pickup_charge_pct: int = 50    # below this the car is not handed out
    min_return_charge_pct: int = 80    # below this the customer pays to recharge
    recharge_fee_per_pct: float = 0.75

    def __post_init__(self) -> None:
        for name in ("min_pickup_charge_pct", "min_return_charge_pct"):
            if not 0 <= getattr(self, name) <= 100:
                raise ValueError(f"{name} must be within 0..100")
        if self.recharge_fee_per_pct < 0:
            raise ValueError("recharge_fee_per_pct must be >= 0")


@dataclass(frozen=True)
class InspectionConfig:
    damage_charges: dict[DamageKind, float] = field(default_factory=lambda: {
        DamageKind.SCRATCH: 150.0,
        DamageKind.DENT: 400.0,
        DamageKind.CRACKED_GLASS: 650.0,
        DamageKind.INTERIOR_STAIN: 120.0,
    })
    needs_repair: frozenset[DamageKind] = frozenset(
        {DamageKind.DENT, DamageKind.CRACKED_GLASS})

    def __post_init__(self) -> None:
        missing = set(DamageKind) - set(self.damage_charges)
        if missing:
            raise ValueError(f"no charge configured for {sorted(k.name for k in missing)}")


@dataclass(frozen=True)
class BranchConfig:
    default_one_way_fee: float = 120.0
    # Directional overrides: (pickup, dropoff) -> fee.
    one_way_fees: dict[tuple[str, str], float] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentConfig:
    deposits: dict[VehicleCategory, float] = field(default_factory=lambda: {
        VehicleCategory.ECONOMY: 200.0,
        VehicleCategory.SUV: 300.0,
        VehicleCategory.LUXURY: 500.0,
    })


@dataclass(frozen=True)
class V2Config:
    pricing: PricingRulesConfig = field(default_factory=PricingRulesConfig)
    ev: EvConfig = field(default_factory=EvConfig)
    inspection: InspectionConfig = field(default_factory=InspectionConfig)
    branches: BranchConfig = field(default_factory=BranchConfig)
    payments: PaymentConfig = field(default_factory=PaymentConfig)
