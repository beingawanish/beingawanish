"""Composition root: the one place that knows every concrete class.

build_desk() builds the v1 parts exactly as v1 expects them, hands the v1
RentalService a RuleChainPricing instead of StandardPricing (a constructor
argument, not an edit), and wraps the result in a RentalDesk.
"""
from collections.abc import Iterable

from car_rental import (
    Clock,
    InMemoryFleet,
    InMemoryReservations,
    RentalConfig,
    RentalService,
    ReservationFactory,
)

from .branches import BranchNetwork, InMemoryTrips, OneWayFeeRule
from .config import V2Config
from .desk import RentalDesk
from .ev import LowChargeRule
from .inspection import DamageInspector
from .lifecycle import InMemoryStatuses, VehicleLifecycle
from .models import Branch, LoyaltyTier
from .payments import PaymentGateway, PaymentService
from .pricing_rules import (
    FleetUtilisation,
    InMemoryLoyalty,
    LongRentalDiscount,
    LoyaltyDiscount,
    RuleChainPricing,
    SurgeRule,
    WeekendRule,
)


def build_desk(*, clock: Clock, gateway: PaymentGateway, branches: Iterable[Branch],
               loyalty: dict[str, LoyaltyTier] | None = None,
               config: V2Config | None = None,
               rental_config: RentalConfig | None = None) -> RentalDesk:
    config = config or V2Config()
    rental_config = rental_config or RentalConfig()

    fleet = InMemoryFleet()
    reservations = InMemoryReservations()
    lifecycle = VehicleLifecycle(InMemoryStatuses(), clock)
    trips = InMemoryTrips()
    network = BranchNetwork(branches, trips, lifecycle, config.branches)

    pricing = RuleChainPricing(
        rules=[WeekendRule(), SurgeRule(),            # surcharges
               LongRentalDiscount(), LoyaltyDiscount(),   # discounts
               OneWayFeeRule(network, trips)],         # flat fee, never discounted
        rules_config=config.pricing,
        utilisation=FleetUtilisation(fleet, reservations),
        loyalty=InMemoryLoyalty(loyalty),
    )
    rental = RentalService(fleet=fleet, reservations=reservations, pricing=pricing,
                           factory=ReservationFactory(fleet, clock),
                           clock=clock, config=rental_config)
    return RentalDesk(
        rental=rental, fleet=fleet, reservations=reservations, pricing=pricing,
        lifecycle=lifecycle, network=network, trips=trips,
        inspector=DamageInspector(config.inspection),
        return_rules=[LowChargeRule(config.ev)],
        payments=PaymentService(gateway),
        clock=clock, config=config, rental_config=rental_config,
    )
