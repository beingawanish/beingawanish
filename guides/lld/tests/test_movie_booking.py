"""Tests for movie ticket booking. Time is frozen via FixedClock throughout."""
import itertools
import sys
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# The guide keeps packages under code/ and tests under tests/. Make the package
# importable when the suite runs from the folder that holds both.
CODE_DIR = Path(__file__).resolve().parent.parent / "code"
if CODE_DIR.is_dir() and str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from movie_booking import (  # noqa: E402
    ALLOWED_TRANSITIONS,
    Booking,
    BookingConfig,
    BookingService,
    BookingStatus,
    Cinema,
    FakePaymentGateway,
    FixedClock,
    HoldExpiredError,
    IdempotencyConflictError,
    InMemoryBookingRepository,
    InMemoryCatalog,
    InvalidConfigError,
    InvalidRequestError,
    InvalidSeatSelectionError,
    InvalidTransitionError,
    Movie,
    PaymentDeclinedError,
    RefundTier,
    SeatInventory,
    SeatType,
    SeatUnavailableError,
    Screen,
    Show,
    ShowClosedError,
    ShowNotFoundError,
    ShowSearch,
    ShowSeatMap,
)

NOW = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
SHOW_AT = NOW + timedelta(days=2)


def make_catalog() -> InMemoryCatalog:
    catalog = InMemoryCatalog()
    catalog.add_cinema(Cinema("C1", "Lakeside Cinemas", "Bengaluru"))
    catalog.add_cinema(Cinema("C2", "Harbour Screens", "Mumbai"))
    catalog.add_screen(Screen.from_rows("SC1", "C1", "Audi 1", [
        ("A", 4, SeatType.REGULAR), ("B", 4, SeatType.PREMIUM), ("C", 2, SeatType.RECLINER),
    ]))
    catalog.add_screen(Screen.from_rows("SC2", "C2", "Audi 1", [("A", 4, SeatType.REGULAR)]))
    catalog.add_movie(Movie("M1", "The Last Monsoon", 148))
    catalog.add_movie(Movie("M2", "Paper Kites", 121))
    catalog.add_show(Show("S1", "M1", "SC1", SHOW_AT))
    catalog.add_show(Show("S2", "M2", "SC1", SHOW_AT + timedelta(hours=4)))
    catalog.add_show(Show("S3", "M1", "SC2", SHOW_AT))
    return catalog


def make_service(gateway: FakePaymentGateway | None = None, start: datetime = NOW):
    clock = FixedClock(start)
    gateway = gateway or FakePaymentGateway()
    ids = itertools.count(1)
    service = BookingService(
        make_catalog(), InMemoryBookingRepository(), gateway,
        config=BookingConfig(), clock=clock, id_factory=lambda: f"BK{next(ids)}",
    )
    return service, clock, gateway


class ConfigTests(unittest.TestCase):
    def test_rejects_non_positive_hold(self):
        with self.assertRaises(InvalidConfigError):
            BookingConfig(hold_seconds=0)

    def test_rejects_missing_seat_price(self):
        with self.assertRaises(InvalidConfigError):
            BookingConfig(seat_prices={SeatType.REGULAR: Decimal("100")})

    def test_rejects_unsorted_refund_tiers(self):
        with self.assertRaises(InvalidConfigError):
            BookingConfig(refund_tiers=(RefundTier(4, 50), RefundTier(24, 100)))


class StateMachineTests(unittest.TestCase):
    def booking(self) -> Booking:
        return Booking("b", "S1", "u", ("A1",), Decimal("200"), NOW)

    def test_held_can_reach_every_other_state(self):
        self.assertEqual(
            ALLOWED_TRANSITIONS[BookingStatus.HELD],
            {BookingStatus.CONFIRMED, BookingStatus.EXPIRED, BookingStatus.CANCELLED},
        )

    def test_terminal_states_go_nowhere(self):
        for status in (BookingStatus.EXPIRED, BookingStatus.CANCELLED):
            b = self.booking()
            b.status = status
            with self.assertRaises(InvalidTransitionError):
                b.transition_to(BookingStatus.CONFIRMED)

    def test_confirmed_cannot_expire(self):
        b = self.booking()
        b.transition_to(BookingStatus.CONFIRMED)
        with self.assertRaises(InvalidTransitionError):
            b.transition_to(BookingStatus.EXPIRED)

    def test_hold_expiry_boundary_is_inclusive(self):
        b = self.booking()
        self.assertFalse(b.is_hold_expired(NOW - timedelta(seconds=1)))
        self.assertTrue(b.is_hold_expired(NOW))


class ShowSeatMapTests(unittest.TestCase):
    def test_claim_is_all_or_nothing(self):
        seats = ShowSeatMap("S1", ["A1", "A2", "A3"])
        seats.claim(["A2"], "x")
        with self.assertRaises(SeatUnavailableError) as ctx:
            seats.claim(["A1", "A2", "A3"], "y")
        self.assertEqual(ctx.exception.seat_ids, ["A2"])
        self.assertEqual(seats.free_seat_ids(), ["A1", "A3"])

    def test_release_frees_only_own_seats(self):
        seats = ShowSeatMap("S1", ["A1", "A2"])
        seats.claim(["A1"], "x")
        seats.release(["A1", "A2"], "someone-else")
        self.assertEqual(seats.owner("A1"), "x")


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.clock = FixedClock(NOW)
        self.search = ShowSearch(make_catalog(), self.clock)

    def test_filters_by_city_case_insensitively_and_sorts(self):
        ids = [listing.show.show_id for listing in self.search.find("  BENGALURU ")]
        self.assertEqual(ids, ["S1", "S2"])

    def test_filters_by_movie_and_date(self):
        found = self.search.find("Bengaluru", movie_id="M1", on_date=SHOW_AT.date())
        self.assertEqual([listing.show.show_id for listing in found], ["S1"])
        self.assertEqual(self.search.find("Bengaluru", on_date=date(2030, 1, 1)), [])

    def test_hides_shows_that_have_started(self):
        self.clock.advance(timedelta(days=2))
        self.assertEqual([listing.show.show_id for listing in self.search.find("Bengaluru")], ["S2"])

    def test_blank_city_rejected(self):
        with self.assertRaises(InvalidRequestError):
            self.search.find(" ")


class HoldTests(unittest.TestCase):
    def setUp(self):
        self.service, self.clock, self.gateway = make_service()

    def test_hold_prices_by_seat_type_and_sets_expiry(self):
        b = self.service.hold_seats("S1", "asha", ["A1", "B1", "C1"])
        self.assertEqual(b.status, BookingStatus.HELD)
        self.assertEqual(b.amount, Decimal("1150.00"))
        self.assertEqual(b.held_until, NOW + timedelta(minutes=10))

    def test_second_user_cannot_take_held_seat(self):
        self.service.hold_seats("S1", "asha", ["A1"])
        with self.assertRaises(SeatUnavailableError):
            self.service.hold_seats("S1", "ravi", ["A1"])

    def test_partial_overlap_fails_whole_request(self):
        self.service.hold_seats("S1", "asha", ["A1", "A2"])
        with self.assertRaises(SeatUnavailableError) as ctx:
            self.service.hold_seats("S1", "ravi", ["A2", "A3"])
        self.assertEqual(ctx.exception.seat_ids, ["A2"])
        free = [o.seat_id for o in self.service.available_seats("S1")]
        self.assertIn("A3", free)

    def test_same_seat_on_different_shows_is_independent(self):
        self.service.hold_seats("S1", "asha", ["A1"])
        self.service.hold_seats("S2", "ravi", ["A1"])

    def test_bad_selections_rejected(self):
        for bad in ([], ["A1", "A1"], ["Z9"], "A1", [f"A{i}" for i in range(11)]):
            with self.subTest(bad=bad), self.assertRaises(InvalidSeatSelectionError):
                self.service.hold_seats("S1", "asha", bad)

    def test_unknown_show_and_blank_user(self):
        with self.assertRaises(ShowNotFoundError):
            self.service.hold_seats("NOPE", "asha", ["A1"])
        with self.assertRaises(InvalidRequestError):
            self.service.hold_seats("S1", " ", ["A1"])

    def test_cannot_hold_after_show_starts(self):
        self.clock.advance(timedelta(days=2))
        with self.assertRaises(ShowClosedError):
            self.service.hold_seats("S1", "asha", ["A1"])

    def test_available_seats_lists_prices(self):
        self.service.hold_seats("S1", "asha", ["C1"])
        offers = {o.seat_id: o.price for o in self.service.available_seats("S1")}
        self.assertNotIn("C1", offers)
        self.assertEqual(offers["C2"], Decimal("600.00"))
        self.assertEqual(len(offers), 9)


class ExpiryTests(unittest.TestCase):
    def setUp(self):
        self.service, self.clock, self.gateway = make_service()

    def test_expired_hold_releases_seat_to_next_user(self):
        first = self.service.hold_seats("S1", "asha", ["A1"])
        self.clock.advance(timedelta(minutes=10))
        second = self.service.hold_seats("S1", "ravi", ["A1"])
        self.assertEqual(first.status, BookingStatus.EXPIRED)
        self.assertEqual(second.status, BookingStatus.HELD)

    def test_one_second_before_expiry_still_held(self):
        self.service.hold_seats("S1", "asha", ["A1"])
        self.clock.advance(timedelta(minutes=10) - timedelta(seconds=1))
        with self.assertRaises(SeatUnavailableError):
            self.service.hold_seats("S1", "ravi", ["A1"])

    def test_confirm_after_expiry_fails_and_charges_nothing(self):
        b = self.service.hold_seats("S1", "asha", ["A1"])
        self.clock.advance(timedelta(minutes=11))
        with self.assertRaises(HoldExpiredError):
            self.service.confirm(b.booking_id, "k1")
        self.assertEqual(b.status, BookingStatus.EXPIRED)
        self.assertEqual(self.gateway.charge_count, 0)

    def test_sweeper_counts_expired_holds(self):
        self.service.hold_seats("S1", "asha", ["A1"])
        self.service.hold_seats("S2", "ravi", ["A1", "A2"])
        self.clock.advance(timedelta(minutes=10))
        self.assertEqual(self.service.expire_holds(), 2)
        self.assertEqual(self.service.expire_holds(), 0)


class PaymentTests(unittest.TestCase):
    def setUp(self):
        self.service, self.clock, self.gateway = make_service()

    def test_confirm_charges_once_and_records_payment(self):
        b = self.service.hold_seats("S1", "asha", ["B1", "B2"])
        self.service.confirm(b.booking_id, "k1")
        self.assertEqual(b.status, BookingStatus.CONFIRMED)
        self.assertEqual(b.payment_id, "pay-1")
        self.assertEqual(self.gateway.total_charged, Decimal("700.00"))

    def test_retry_with_same_key_is_a_no_op(self):
        b = self.service.hold_seats("S1", "asha", ["A1"])
        self.service.confirm(b.booking_id, "k1")
        again = self.service.confirm(b.booking_id, "k1")
        self.assertIs(again, b)
        self.assertEqual(self.gateway.charge_count, 1)

    def test_second_confirm_with_new_key_rejected(self):
        b = self.service.hold_seats("S1", "asha", ["A1"])
        self.service.confirm(b.booking_id, "k1")
        with self.assertRaises(InvalidTransitionError):
            self.service.confirm(b.booking_id, "k2")
        self.assertEqual(self.gateway.charge_count, 1)

    def test_key_reused_for_other_booking_rejected(self):
        b1 = self.service.hold_seats("S1", "asha", ["A1"])
        b2 = self.service.hold_seats("S1", "asha", ["A2"])
        self.service.confirm(b1.booking_id, "k1")
        with self.assertRaises(IdempotencyConflictError):
            self.service.confirm(b2.booking_id, "k1")

    def test_decline_keeps_hold_and_retry_succeeds(self):
        service, _, gateway = make_service(FakePaymentGateway(decline_users={"ravi"}))
        b = service.hold_seats("S1", "ravi", ["A1"])
        with self.assertRaises(PaymentDeclinedError):
            service.confirm(b.booking_id, "k1")
        self.assertEqual(b.status, BookingStatus.HELD)
        gateway.decline_users.discard("ravi")  # the user switches cards
        service.confirm(b.booking_id, "k2")
        self.assertEqual(b.status, BookingStatus.CONFIRMED)

    def test_hold_lost_during_payment_is_refunded(self):
        gateway = FakePaymentGateway()
        service, clock, _ = make_service(gateway)
        b = service.hold_seats("S1", "asha", ["A1"])

        def slow_payment():  # the gateway takes 11 minutes; the sweeper runs meanwhile
            clock.advance(timedelta(minutes=11))
            service.expire_holds("S1")

        gateway.after_charge = slow_payment
        with self.assertRaises(HoldExpiredError), self.assertLogs("movie_booking", "WARNING"):
            service.confirm(b.booking_id, "k1")
        self.assertEqual(b.status, BookingStatus.EXPIRED)
        self.assertEqual(gateway.total_refunded, gateway.total_charged)

    def test_blank_key_rejected(self):
        b = self.service.hold_seats("S1", "asha", ["A1"])
        with self.assertRaises(InvalidRequestError):
            self.service.confirm(b.booking_id, "  ")


class CancellationTests(unittest.TestCase):
    def setUp(self):
        self.service, self.clock, self.gateway = make_service()

    def confirmed(self, seats=("B1", "B2")):
        b = self.service.hold_seats("S1", "asha", list(seats))
        return self.service.confirm(b.booking_id, f"k-{b.booking_id}")

    def test_cancel_hold_frees_seats_without_refund(self):
        b = self.service.hold_seats("S1", "asha", ["A1"])
        self.service.cancel(b.booking_id)
        self.assertEqual(b.status, BookingStatus.CANCELLED)
        self.assertEqual(self.gateway.total_refunded, Decimal("0.00"))
        self.service.hold_seats("S1", "ravi", ["A1"])

    def test_full_refund_a_day_or_more_ahead(self):
        b = self.confirmed()
        self.service.cancel(b.booking_id)
        self.assertEqual(b.refund_amount, Decimal("700.00"))
        self.assertEqual(self.gateway.total_refunded, Decimal("700.00"))

    def test_half_refund_between_four_and_24_hours(self):
        b = self.confirmed()
        self.clock.advance(timedelta(days=1, hours=20))  # exactly 4h before the show
        self.service.cancel(b.booking_id)
        self.assertEqual(b.refund_amount, Decimal("350.00"))

    def test_no_refund_inside_four_hours(self):
        b = self.confirmed()
        self.clock.advance(timedelta(days=1, hours=21))
        self.service.cancel(b.booking_id)
        self.assertEqual(b.refund_amount, Decimal("0.00"))
        self.assertEqual(self.gateway.total_refunded, Decimal("0.00"))

    def test_cannot_cancel_after_show_starts(self):
        b = self.confirmed()
        self.clock.advance(timedelta(days=2))
        with self.assertRaises(ShowClosedError):
            self.service.cancel(b.booking_id)

    def test_cannot_cancel_twice_or_cancel_expired(self):
        b = self.confirmed()
        self.service.cancel(b.booking_id)
        with self.assertRaises(InvalidTransitionError):
            self.service.cancel(b.booking_id)
        held = self.service.hold_seats("S1", "ravi", ["A4"])
        self.clock.advance(timedelta(minutes=10))
        with self.assertRaises(InvalidTransitionError):
            self.service.cancel(held.booking_id)


class ConcurrencyTests(unittest.TestCase):
    THREADS = 20

    def test_many_users_one_seat_exactly_one_winner(self):
        service, _, _ = make_service()
        barrier = threading.Barrier(self.THREADS)
        wins, losses = [], []

        def attempt(user: str) -> None:
            barrier.wait()
            try:
                wins.append(service.hold_seats("S1", user, ["C1", "C2"]))
            except SeatUnavailableError:
                losses.append(user)

        threads = [threading.Thread(target=attempt, args=(f"u{i}",)) for i in range(self.THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(wins), 1)
        self.assertEqual(len(losses), self.THREADS - 1)

    def test_concurrent_confirms_with_same_key_charge_once(self):
        service, _, gateway = make_service()
        b = service.hold_seats("S1", "asha", ["A1"])
        barrier = threading.Barrier(self.THREADS)
        results = []

        def attempt() -> None:
            barrier.wait()
            results.append(service.confirm(b.booking_id, "same-key").status)

        threads = [threading.Thread(target=attempt) for _ in range(self.THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results, [BookingStatus.CONFIRMED] * self.THREADS)
        self.assertEqual(gateway.charge_count, 1)

    def test_each_show_gets_its_own_lock(self):
        inventory = SeatInventory(make_catalog())
        self.assertIs(inventory.for_show("S1"), inventory.for_show("S1"))
        self.assertIsNot(inventory.for_show("S1").lock, inventory.for_show("S2").lock)


if __name__ == "__main__":
    unittest.main()
