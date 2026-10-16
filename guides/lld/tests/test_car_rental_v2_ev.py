"""Version 2, feature 2: EV fleet, charge level, low-charge return rule."""
import unittest
from datetime import date

from car_rental import DuplicateVehicleError, FixedClock, Vehicle, VehicleCategory
from car_rental_v2 import (
    Branch,
    ElectricVehicle,
    EvConfig,
    InMemoryPaymentGateway,
    InspectionReport,
    LowChargeRule,
    VehicleNotReadyError,
    VehicleState,
    build_desk,
)

TODAY = date(2026, 10, 15)


def make_desk(charge_pct=90):
    clock = FixedClock(TODAY)
    desk = build_desk(clock=clock, gateway=InMemoryPaymentGateway(),
                      branches=[Branch("DT", "Downtown")])
    desk.add_ev("EV-01", VehicleCategory.LUXURY, "Polestar", "2", 2025, "DT",
                battery_kwh=78.0, charge_pct=charge_pct)
    return desk, clock


def ev(charge_pct):
    return ElectricVehicle("EV-01", VehicleCategory.LUXURY, "Polestar", "2", 2025,
                           battery_kwh=78.0, charge_pct=charge_pct)


class ElectricVehicleTests(unittest.TestCase):
    def test_an_ev_is_a_v1_vehicle_and_v1_search_finds_it(self):
        desk, _ = make_desk()
        found = desk.search(VehicleCategory.LUXURY, TODAY, date(2026, 10, 17), "DT")
        self.assertEqual([v.vehicle_id for v in found], ["EV-01"])
        self.assertIsInstance(found[0], Vehicle)

    def test_bad_ev_input_is_rejected(self):
        desk, _ = make_desk()
        with self.assertRaises(ValueError):
            desk.add_ev("EV-02", VehicleCategory.LUXURY, "Polestar", "2", 2025, "DT",
                        battery_kwh=78.0, charge_pct=101)
        with self.assertRaises(DuplicateVehicleError):
            desk.add_ev("EV-01", VehicleCategory.LUXURY, "Polestar", "2", 2025, "DT",
                        battery_kwh=78.0, charge_pct=90)

    def test_pickup_refused_below_minimum_charge(self):
        desk, _ = make_desk(charge_pct=40)
        trip = desk.book("EV-01", "Jacob", TODAY, date(2026, 10, 17), "DT")
        with self.assertRaises(VehicleNotReadyError):
            desk.pick_up(trip.reservation_id)


class LowChargeRuleTests(unittest.TestCase):
    rule = LowChargeRule(EvConfig())

    def test_shortfall_is_charged_per_point(self):
        lines = self.rule.charges(ev(90), InspectionReport(charge_pct=35))
        self.assertEqual(lines[0].amount, 33.75)   # (80 - 35) x 0.75

    def test_at_threshold_is_free(self):
        self.assertEqual(self.rule.charges(ev(90), InspectionReport(charge_pct=80)), [])

    def test_petrol_cars_are_ignored(self):
        car = Vehicle("ECO-01", VehicleCategory.ECONOMY, "Toyota", "Corolla", 2023)
        self.assertEqual(self.rule.charges(car, InspectionReport()), [])

    def test_ev_return_needs_a_charge_reading(self):
        with self.assertRaises(ValueError):
            self.rule.charges(ev(90), InspectionReport())


class ChargingFlowTests(unittest.TestCase):
    def test_low_return_goes_to_charging_then_back_to_available(self):
        desk, clock = make_desk()
        trip = desk.book("EV-01", "Jacob", TODAY, date(2026, 10, 17), "DT")
        desk.pick_up(trip.reservation_id)
        clock.advance(2)
        desk.return_vehicle(trip.reservation_id)
        summary = desk.complete_inspection(trip.reservation_id,
                                           InspectionReport(charge_pct=30))
        self.assertIs(summary.next_state, VehicleState.CHARGING)
        nxt = desk.book("EV-01", "Shyam Miyatra", clock.today(), date(2026, 10, 19), "DT")
        with self.assertRaises(VehicleNotReadyError):
            desk.pick_up(nxt.reservation_id)
        desk.finish_charging("EV-01", 95)
        self.assertIs(desk.status("EV-01").state, VehicleState.AVAILABLE)
        desk.pick_up(nxt.reservation_id)

    def test_finish_charging_below_pickup_minimum_is_rejected(self):
        desk, clock = make_desk()
        trip = desk.book("EV-01", "Jacob", TODAY, date(2026, 10, 17), "DT")
        desk.pick_up(trip.reservation_id)
        clock.advance(2)
        desk.return_vehicle(trip.reservation_id)
        desk.complete_inspection(trip.reservation_id, InspectionReport(charge_pct=30))
        with self.assertRaises(ValueError):
            desk.finish_charging("EV-01", 45)


if __name__ == "__main__":
    unittest.main()
