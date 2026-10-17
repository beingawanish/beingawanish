"""Version 2, feature 4: multi-branch pickup and drop-off, one-way fee."""
import unittest
from datetime import date

from car_rental import FixedClock, VehicleCategory
from car_rental_v2 import (
    Branch,
    BranchConfig,
    BranchMismatchError,
    InMemoryPaymentGateway,
    InspectionReport,
    UnknownBranchError,
    V2Config,
    build_desk,
)

TODAY = date(2026, 10, 15)
MON, WED, FRI = date(2026, 10, 19), date(2026, 10, 21), date(2026, 10, 23)


def make_desk(config=None):
    clock = FixedClock(TODAY)
    desk = build_desk(clock=clock, gateway=InMemoryPaymentGateway(), config=config,
                      branches=[Branch("DT", "Downtown"), Branch("AP", "Airport")])
    desk.add_vehicle("ECO-01", VehicleCategory.ECONOMY, "Toyota", "Corolla", 2023, "DT")
    return desk, clock


def fee_lines(desk, trip):
    return [l for l in desk.quote(trip.reservation_id).lines
            if l.label.startswith("one-way")]


class OneWayFeeTests(unittest.TestCase):
    def test_round_trip_has_no_fee(self):
        desk, _ = make_desk()
        trip = desk.book("ECO-01", "Jacob", MON, WED, "DT")
        self.assertEqual(fee_lines(desk, trip), [])

    def test_one_way_uses_the_default_fee(self):
        desk, _ = make_desk()
        trip = desk.book("ECO-01", "Jacob", MON, WED, "DT", "AP")
        self.assertEqual(fee_lines(desk, trip)[0].amount, 120.0)
        self.assertEqual(trip.quoted_total, round(99.98 + 120.0, 2))

    def test_route_override_is_directional(self):
        config = V2Config(branches=BranchConfig(one_way_fees={("DT", "AP"): 80.0}))
        desk, _ = make_desk(config)
        trip = desk.book("ECO-01", "Jacob", MON, WED, "DT", "AP")
        back = desk.book("ECO-01", "Jacob", WED, FRI, "AP", "DT")
        self.assertEqual(fee_lines(desk, trip)[0].amount, 80.0)
        self.assertEqual(fee_lines(desk, back)[0].amount, 120.0)


class RouteTests(unittest.TestCase):
    def test_pickup_must_be_where_the_car_will_be(self):
        desk, _ = make_desk()
        with self.assertRaises(BranchMismatchError):
            desk.book("ECO-01", "Jacob", MON, WED, "AP")

    def test_one_way_trip_moves_the_car_for_later_bookings(self):
        desk, _ = make_desk()
        desk.book("ECO-01", "Jacob", MON, WED, "DT", "AP")
        with self.assertRaises(BranchMismatchError):
            desk.book("ECO-01", "Shyam Miyatra", WED, FRI, "DT")
        desk.book("ECO-01", "Shyam Miyatra", WED, FRI, "AP")

    def test_one_way_trip_cannot_strand_a_later_booking(self):
        desk, _ = make_desk()
        desk.book("ECO-01", "Shyam Miyatra", WED, FRI, "DT")
        with self.assertRaises(BranchMismatchError):
            desk.book("ECO-01", "Jacob", MON, WED, "DT", "AP")

    def test_cancelling_the_one_way_trip_puts_the_car_back(self):
        desk, _ = make_desk()
        trip = desk.book("ECO-01", "Jacob", MON, WED, "DT", "AP")
        desk.cancel(trip.reservation_id)
        desk.book("ECO-01", "Shyam Miyatra", WED, FRI, "DT")

    def test_search_is_per_branch_and_follows_the_route(self):
        desk, _ = make_desk()
        desk.book("ECO-01", "Jacob", MON, WED, "DT", "AP")
        ids = lambda b: [v.vehicle_id for v in
                         desk.search(VehicleCategory.ECONOMY, WED, FRI, b)]
        self.assertEqual(ids("DT"), [])
        self.assertEqual(ids("AP"), ["ECO-01"])

    def test_return_moves_the_car_to_the_dropoff_branch(self):
        desk, clock = make_desk()
        trip = desk.book("ECO-01", "Jacob", TODAY, date(2026, 10, 17), "DT", "AP")
        desk.pick_up(trip.reservation_id)
        clock.advance(2)
        desk.return_vehicle(trip.reservation_id)
        desk.complete_inspection(trip.reservation_id, InspectionReport())
        self.assertEqual(desk.status("ECO-01").branch_id, "AP")

    def test_unknown_branch_is_rejected(self):
        desk, _ = make_desk()
        with self.assertRaises(UnknownBranchError):
            desk.book("ECO-01", "Jacob", MON, WED, "DT", "XX")


if __name__ == "__main__":
    unittest.main()
