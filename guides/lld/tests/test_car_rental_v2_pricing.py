"""Version 2, feature 1: dynamic pricing as a rule chain."""
import unittest
from datetime import date

from car_rental import (
    FixedClock,
    InMemoryFleet,
    InMemoryReservations,
    RentalConfig,
    RentalService,
    Reservation,
    Vehicle,
    VehicleCategory,
)
from car_rental_v2 import (
    Branch,
    FleetUtilisation,
    InMemoryLoyalty,
    InMemoryPaymentGateway,
    LongRentalDiscount,
    LoyaltyDiscount,
    LoyaltyTier,
    PricingContext,
    PricingRulesConfig,
    RuleChainPricing,
    SurgeRule,
    WeekendRule,
    build_desk,
)

TODAY = date(2026, 10, 15)                       # a Thursday
MON, THU = date(2026, 10, 19), date(2026, 10, 22)  # weekdays only
FRI, MON2 = date(2026, 10, 23), date(2026, 10, 26)  # Fri, Sat, Sun


def make_desk(economy_cars=2, loyalty=None):
    desk = build_desk(clock=FixedClock(TODAY), gateway=InMemoryPaymentGateway(),
                      branches=[Branch("DT", "Downtown"), Branch("AP", "Airport")],
                      loyalty=loyalty)
    for i in range(1, economy_cars + 1):
        desk.add_vehicle(f"ECO-0{i}", VehicleCategory.ECONOMY,
                         "Toyota", "Corolla", 2023, "DT")
    return desk


def labels(quote):
    return [line.label for line in quote.lines]


def context(days, tier=LoyaltyTier.NONE, utilisation=0.0):
    start = MON
    end = date.fromordinal(start.toordinal() + days)
    return PricingContext(
        vehicle=Vehicle("ECO-01", VehicleCategory.ECONOMY, "Toyota", "Corolla", 2023),
        reservation=Reservation("r1", "ECO-01", "Awanish Singh", start, end),
        daily_rate=50.0, utilisation=utilisation, tier=tier,
        rules=PricingRulesConfig())


class RuleTests(unittest.TestCase):
    def test_weekday_rental_has_no_weekend_line(self):
        desk = make_desk()
        trip = desk.book("ECO-01", "Jacob", MON, THU, "DT")
        self.assertEqual(labels(desk.quote(trip.reservation_id)), ["standard"])
        self.assertEqual(trip.quoted_total, 149.97)

    def test_weekend_days_cost_twenty_percent_more(self):
        desk = make_desk()
        trip = desk.book("ECO-01", "Jacob", FRI, MON2, "DT")
        lines = desk.quote(trip.reservation_id).lines
        self.assertEqual(lines[1].label, "weekend x2")
        self.assertEqual(lines[1].amount, 20.00)   # 2 x 49.99 x 0.2

    def test_surge_follows_the_tiers(self):
        for others_booked, expected in [(2, None), (3, 0.10), (4, 0.25)]:
            with self.subTest(others_booked=others_booked):
                desk = make_desk(economy_cars=5)
                for i in range(2, 2 + others_booked):
                    desk.book(f"ECO-0{i}", "Shyam Miyatra", MON, THU, "DT")
                trip = desk.book("ECO-01", "Jacob", MON, THU, "DT")
                surge = [l for l in desk.quote(trip.reservation_id).lines
                         if l.label.startswith("surge")]
                if expected is None:
                    self.assertEqual(surge, [])
                else:
                    self.assertEqual(surge[0].amount, round(149.97 * expected, 2))

    def test_long_rental_discount_starts_at_seven_days(self):
        rule = LongRentalDiscount()
        self.assertIsNone(rule.adjust(context(6), 300.0))
        self.assertEqual(rule.adjust(context(7), 350.0).amount, -35.0)

    def test_loyalty_discount_by_tier(self):
        rule = LoyaltyDiscount()
        self.assertIsNone(rule.adjust(context(3), 150.0))
        self.assertEqual(rule.adjust(context(3, LoyaltyTier.SILVER), 150.0).amount, -7.5)
        self.assertEqual(rule.adjust(context(3, LoyaltyTier.GOLD), 150.0).amount, -15.0)

    def test_weekend_and_surge_rules_are_independent(self):
        self.assertIsNone(SurgeRule().adjust(context(3, utilisation=0.49), 150.0))
        self.assertIsNone(WeekendRule().adjust(context(4), 200.0))   # Mon..Thu


class ChainTests(unittest.TestCase):
    def test_discount_sees_surcharges_but_not_the_one_way_fee(self):
        desk = make_desk(loyalty={"Awanish Singh": LoyaltyTier.GOLD})
        desk.book("ECO-02", "Shyam Miyatra", FRI, MON2, "DT")
        trip = desk.book("ECO-01", "Awanish Singh", FRI, MON2, "DT", "AP")
        quote = desk.quote(trip.reservation_id)
        self.assertEqual(labels(quote), ["standard", "weekend x2", "surge (50% booked)",
                                         "loyalty GOLD", "one-way DT->AP"])
        # 10% of 149.97 + 20.00 + 15.00 = 184.97, the fee is added after.
        self.assertEqual(quote.lines[3].amount, -18.50)
        self.assertEqual(quote.total, 286.47)

    def test_chain_plugs_into_the_untouched_v1_service(self):
        fleet, reservations = InMemoryFleet(), InMemoryReservations()
        chain = RuleChainPricing(
            rules=[WeekendRule(), SurgeRule(), LongRentalDiscount(), LoyaltyDiscount()],
            rules_config=PricingRulesConfig(),
            utilisation=FleetUtilisation(fleet, reservations),
            loyalty=InMemoryLoyalty({"Awanish Singh": LoyaltyTier.GOLD}))
        v1 = RentalService(fleet=fleet, reservations=reservations, pricing=chain,
                           clock=FixedClock(TODAY), config=RentalConfig())
        v1.add_vehicle("ECO-01", VehicleCategory.ECONOMY, "Toyota", "Corolla", 2023)
        r = v1.reserve("ECO-01", "Awanish Singh", MON, THU)
        self.assertEqual(v1.quote(r.reservation_id), 134.97)   # 149.97 - 15.00

    def test_price_is_locked_at_booking(self):
        desk = make_desk()
        trip = desk.book("ECO-01", "Jacob", MON, THU, "DT")
        desk.book("ECO-02", "Shyam Miyatra", MON, THU, "DT")   # now 50% booked
        self.assertEqual(desk.quote(trip.reservation_id).total, 164.97)
        self.assertEqual(trip.quoted_total, 149.97)


class PricingConfigTests(unittest.TestCase):
    def test_discount_of_100_percent_is_rejected(self):
        with self.assertRaises(ValueError):
            PricingRulesConfig(long_rental_discount=1.0)

    def test_surge_tiers_must_be_ordered(self):
        with self.assertRaises(ValueError):
            PricingRulesConfig(surge_tiers=((0.5, 1.1), (0.8, 1.25)))


if __name__ == "__main__":
    unittest.main()
