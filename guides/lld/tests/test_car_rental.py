"""Tests for car rental. Time is frozen via FixedClock throughout."""
import threading
import unittest
from datetime import date

from car_rental import (
    AddOns,
    AlreadyCancelledError,
    FixedClock,
    InMemoryFleet,
    InMemoryReservations,
    InvalidDateRangeError,
    RentalConfig,
    RentalService,
    Reservation,
    ReservationConflictError,
    ReservationFactory,
    ReservationInPastError,
    ReservationNotFoundError,
    StandardPricing,
    VehicleCategory,
    VehicleNotFoundError,
)

TODAY = date(2026, 10, 15)
EXISTING_START = date(2026, 11, 1)
EXISTING_END = date(2026, 11, 5)


def make_service(today=TODAY):
    clock = FixedClock(today)
    fleet = InMemoryFleet()
    reservations = InMemoryReservations()
    factory = ReservationFactory(fleet, clock)
    svc = RentalService(
        fleet=fleet, reservations=reservations,
        pricing=StandardPricing(), factory=factory,
        clock=clock, config=RentalConfig(),
    )
    svc.add_vehicle("ECO-01", VehicleCategory.ECONOMY, "Toyota", "Corolla", 2023)
    svc.add_vehicle("ECO-02", VehicleCategory.ECONOMY, "Honda", "Civic", 2022)
    svc.add_vehicle("SUV-01", VehicleCategory.SUV, "Honda", "CR-V", 2024)
    return svc, clock


class OverlapRuleTests(unittest.TestCase):
    """The half-open rule, case by case, against [Nov 1, Nov 5)."""

    def check(self, start, end, expected):
        existing = Reservation("r1", "ECO-01", "Awanish Singh",
                               EXISTING_START, EXISTING_END)
        self.assertEqual(existing.conflicts_with(start, end), expected,
                         f"[{start}, {end}) vs [Nov 1, Nov 5)")

    def test_ends_when_existing_starts_is_free(self):
        self.check(date(2026, 10, 28), date(2026, 11, 1), False)

    def test_starts_when_existing_ends_is_free(self):
        self.check(date(2026, 11, 5), date(2026, 11, 8), False)

    def test_identical_window_conflicts(self):
        self.check(EXISTING_START, EXISTING_END, True)

    def test_inside_existing_conflicts(self):
        self.check(date(2026, 11, 2), date(2026, 11, 4), True)

    def test_wrapping_existing_conflicts(self):
        self.check(date(2026, 10, 30), date(2026, 11, 6), True)

    def test_overlap_at_start_conflicts(self):
        self.check(date(2026, 10, 30), date(2026, 11, 2), True)

    def test_overlap_at_end_conflicts(self):
        self.check(date(2026, 11, 4), date(2026, 11, 8), True)

    def test_same_start_conflicts(self):
        self.check(date(2026, 11, 1), date(2026, 11, 2), True)


class BookingTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.clock = make_service()

    def test_back_to_back_booking_is_allowed(self):
        self.svc.reserve("ECO-01", "Awanish Singh", EXISTING_START, EXISTING_END)
        second = self.svc.reserve("ECO-01", "Shyam Miyatra",
                                  EXISTING_END, date(2026, 11, 8))
        self.assertEqual(second.start_date, EXISTING_END)

    def test_overlapping_booking_raises_conflict(self):
        self.svc.reserve("ECO-01", "Awanish Singh", EXISTING_START, EXISTING_END)
        with self.assertRaises(ReservationConflictError):
            self.svc.reserve("ECO-01", "Jacob",
                             date(2026, 11, 4), date(2026, 11, 7))

    def test_same_window_on_different_vehicle_is_fine(self):
        self.svc.reserve("ECO-01", "Awanish Singh", EXISTING_START, EXISTING_END)
        other = self.svc.reserve("ECO-02", "Jacob", EXISTING_START, EXISTING_END)
        self.assertEqual(other.vehicle_id, "ECO-02")

    def test_cancel_frees_the_window(self):
        r = self.svc.reserve("ECO-01", "Awanish Singh",
                             EXISTING_START, EXISTING_END)
        self.svc.cancel(r.reservation_id)
        again = self.svc.reserve("ECO-01", "Jacob", EXISTING_START, EXISTING_END)
        self.assertFalse(again.cancelled)

    def test_double_cancel_raises(self):
        r = self.svc.reserve("ECO-01", "Awanish Singh",
                             EXISTING_START, EXISTING_END)
        self.svc.cancel(r.reservation_id)
        with self.assertRaises(AlreadyCancelledError):
            self.svc.cancel(r.reservation_id)

    def test_cancel_unknown_raises(self):
        with self.assertRaises(ReservationNotFoundError):
            self.svc.cancel("nope")


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.clock = make_service()

    def test_end_before_start_raises(self):
        with self.assertRaises(InvalidDateRangeError):
            self.svc.reserve("ECO-01", "Awanish Singh",
                             date(2026, 11, 5), date(2026, 11, 1))

    def test_zero_day_rental_raises(self):
        with self.assertRaises(InvalidDateRangeError):
            self.svc.reserve("ECO-01", "Awanish Singh",
                             date(2026, 11, 5), date(2026, 11, 5))

    def test_start_in_past_raises(self):
        with self.assertRaises(ReservationInPastError):
            self.svc.reserve("ECO-01", "Awanish Singh",
                             date(2026, 10, 10), date(2026, 10, 12))

    def test_unknown_vehicle_raises(self):
        with self.assertRaises(VehicleNotFoundError):
            self.svc.reserve("NOPE", "Awanish Singh",
                             EXISTING_START, EXISTING_END)

    def test_blank_customer_raises(self):
        with self.assertRaises(ValueError):
            self.svc.reserve("ECO-01", "   ", EXISTING_START, EXISTING_END)

    def test_search_validates_range(self):
        with self.assertRaises(InvalidDateRangeError):
            self.svc.search_available(VehicleCategory.ECONOMY,
                                      EXISTING_END, EXISTING_START)


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.clock = make_service()

    def test_suv_three_days_with_addons(self):
        r = self.svc.reserve("SUV-01", "Awanish Singh",
                             date(2026, 11, 1), date(2026, 11, 4),
                             AddOns(insurance=True, gps=True))
        # 3 x 89.99 + 3 x 9.99 + 3 x 4.99
        self.assertEqual(self.svc.quote(r.reservation_id), 314.91)

    def test_economy_two_days_no_addons(self):
        r = self.svc.reserve("ECO-01", "Awanish Singh",
                             date(2026, 11, 1), date(2026, 11, 3))
        self.assertEqual(self.svc.quote(r.reservation_id), 99.98)

    def test_on_time_return_has_no_late_fee(self):
        r = self.svc.reserve("ECO-01", "Awanish Singh",
                             date(2026, 11, 1), date(2026, 11, 4))
        self.assertEqual(self.svc.return_vehicle(r.reservation_id,
                                                 date(2026, 11, 4)), 0.0)

    def test_two_days_late_fee(self):
        r = self.svc.reserve("ECO-01", "Awanish Singh",
                             date(2026, 11, 1), date(2026, 11, 4))
        self.assertEqual(self.svc.return_vehicle(r.reservation_id,
                                                 date(2026, 11, 6)), 159.98)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.clock = make_service()

    def test_search_returns_only_free_vehicles_of_category(self):
        self.svc.reserve("ECO-01", "Awanish Singh", EXISTING_START, EXISTING_END)
        free = self.svc.search_available(VehicleCategory.ECONOMY,
                                         EXISTING_START, EXISTING_END)
        self.assertEqual([v.vehicle_id for v in free], ["ECO-02"])

    def test_search_excludes_other_categories(self):
        free = self.svc.search_available(VehicleCategory.SUV,
                                         EXISTING_START, EXISTING_END)
        self.assertEqual([v.vehicle_id for v in free], ["SUV-01"])


class ConcurrencyTests(unittest.TestCase):
    def test_same_window_goes_to_exactly_one_thread(self):
        svc, _ = make_service()
        barrier = threading.Barrier(2)
        outcomes = []

        def attempt(name):
            barrier.wait()
            try:
                svc.reserve("SUV-01", name, EXISTING_START, EXISTING_END)
                outcomes.append("ok")
            except ReservationConflictError:
                outcomes.append("conflict")

        threads = [threading.Thread(target=attempt, args=(n,))
                   for n in ("Awanish Singh", "Shyam Miyatra")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(outcomes), ["conflict", "ok"])


if __name__ == "__main__":
    unittest.main()
