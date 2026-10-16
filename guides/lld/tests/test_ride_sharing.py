"""Tests for ride sharing. Time moves only through ManualClock."""
import threading
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ride_sharing import (
    ALLOWED,
    CancelledBy,
    DriverBusyError,
    DriverStatus,
    EventKind,
    GracePeriodCancellation,
    GridIndex,
    IllegalTransitionError,
    InMemoryDrivers,
    InvalidInputError,
    Location,
    ManualClock,
    NearestDriverStrategy,
    OfferExpiredError,
    OfferNotFoundError,
    RatingBook,
    RatingError,
    RatingWeightedStrategy,
    RecordingObserver,
    RideConfig,
    RideService,
    RiderNotFoundError,
    StandardFare,
    SupplyDemandSurge,
    Trip,
    TripObserver,
    TripStatus,
    transition,
)
from ride_sharing.models import Driver

START = datetime(2026, 10, 16, 18, 0, tzinfo=UTC)
HOME = Location(0.0, 0.0)
OFFICE = Location(3.0, 4.0)  # 5 km from HOME


def make_service(config=None, matching=None):
    config = config or RideConfig()
    clock = ManualClock(START)
    recorder = RecordingObserver()
    service = RideService(config=config, clock=clock, matching=matching)
    service.subscribe(recorder)
    service.register_rider("r1", "Awanish")
    return service, clock, recorder


def add_driver(service, driver_id, x, y, online=True):
    service.register_driver(driver_id, driver_id.title(), Location(x, y))
    if online:
        service.go_online(driver_id)


def offer_of(service, trip):
    return service.pending_offer(trip.trip_id)


def matched_trip(service, driver_id="d1"):
    add_driver(service, driver_id, 0.5, 0.0)
    trip = service.request_ride("r1", HOME, OFFICE)
    service.accept_offer(offer_of(service, trip).offer_id)
    return trip


class GridIndexTests(unittest.TestCase):
    def test_within_returns_nearest_first_and_respects_radius(self):
        index = GridIndex(1.0)
        index.upsert("far", Location(2.9, 0.0))
        index.upsert("near", Location(0.2, 0.0))
        index.upsert("out", Location(3.1, 0.0))
        found = [d for d, _ in index.within(HOME, 3.0)]
        self.assertEqual(found, ["near", "far"])

    def test_negative_coordinates_and_cell_edges(self):
        index = GridIndex(1.0)
        index.upsert("west", Location(-0.01, 0.0))
        self.assertEqual(index.cell_of(Location(-0.01, 0.0)), (-1, 0))
        self.assertEqual([d for d, _ in index.within(Location(0.01, 0.0), 0.05)], ["west"])

    def test_upsert_moves_driver_between_cells(self):
        index = GridIndex(1.0)
        index.upsert("d1", Location(0.5, 0.5))
        index.upsert("d1", Location(9.5, 9.5))
        self.assertEqual(index.within(HOME, 2.0), [])
        self.assertEqual([d for d, _ in index.within(Location(9.0, 9.0), 1.0)], ["d1"])

    def test_remove_and_bad_input(self):
        index = GridIndex(1.0)
        index.upsert("d1", HOME)
        index.remove("d1")
        index.remove("never-added")
        self.assertEqual(index.within(HOME, 5.0), [])
        with self.assertRaises(InvalidInputError):
            GridIndex(0)


class MatchingTests(unittest.TestCase):
    def drivers(self):
        close = Driver("close", "Close", Location(1.0, 0.0), ratings=RatingBook(40, 10))
        better = Driver("better", "Better", Location(1.4, 0.0), ratings=RatingBook(50, 10))
        return [better, close]

    def test_nearest_picks_shortest_distance(self):
        ranked = NearestDriverStrategy().rank(HOME, self.drivers())
        self.assertEqual([d.driver_id for d in ranked], ["close", "better"])

    def test_rating_weighted_trades_distance_for_stars(self):
        ranked = RatingWeightedStrategy(RideConfig()).rank(HOME, self.drivers())
        self.assertEqual([d.driver_id for d in ranked], ["better", "close"])

    def test_unrated_driver_uses_default_and_ties_break_by_id(self):
        a = Driver("a", "A", Location(1.0, 0.0))
        b = Driver("b", "B", Location(0.0, 1.0))
        ranked = RatingWeightedStrategy(RideConfig()).rank(HOME, [b, a])
        self.assertEqual([d.driver_id for d in ranked], ["a", "b"])


class LifecycleTests(unittest.TestCase):
    def trip(self, status):
        return Trip("T", "r1", HOME, OFFICE, START, Decimal("1.0"), status=status)

    def test_every_allowed_edge_works(self):
        for source, targets in ALLOWED.items():
            for target in targets:
                trip = self.trip(source)
                transition(trip, target)
                self.assertIs(trip.status, target)

    def test_every_other_edge_raises_and_changes_nothing(self):
        for source in TripStatus:
            for target in TripStatus:
                if target in ALLOWED[source]:
                    continue
                trip = self.trip(source)
                with self.assertRaises(IllegalTransitionError):
                    transition(trip, target)
                self.assertIs(trip.status, source)

    def test_terminal_states_have_no_exits(self):
        self.assertEqual(ALLOWED[TripStatus.COMPLETED], frozenset())
        self.assertEqual(ALLOWED[TripStatus.CANCELLED], frozenset())

    def test_service_refuses_skipping_a_state(self):
        service, _, _ = make_service()
        trip = matched_trip(service)
        with self.assertRaises(IllegalTransitionError):
            service.start_trip(trip.trip_id)  # MATCHED -> IN_PROGRESS skips arriving


class SurgeAndFareTests(unittest.TestCase):
    def setUp(self):
        self.surge = SupplyDemandSurge(RideConfig())
        self.fares = StandardFare(RideConfig())

    def test_no_surge_while_supply_keeps_up(self):
        self.assertEqual(self.surge.multiplier(demand=3, supply=3), Decimal("1.0"))

    def test_surge_grows_with_ratio_and_rounds_to_a_tenth(self):
        self.assertEqual(self.surge.multiplier(demand=2, supply=1), Decimal("1.5"))
        self.assertEqual(self.surge.multiplier(demand=4, supply=3), Decimal("1.2"))

    def test_surge_is_capped_and_zero_supply_hits_the_cap(self):
        self.assertEqual(self.surge.multiplier(demand=50, supply=1), Decimal("2.5"))
        self.assertEqual(self.surge.multiplier(demand=1, supply=0), Decimal("2.5"))

    def test_standard_fare(self):
        # 2.50 + 1.20 * 5 + 0.30 * 10 = 11.50
        self.assertEqual(self.fares.fare(5.0, 10.0, Decimal("1.0")), Decimal("11.50"))
        self.assertEqual(self.fares.fare(5.0, 10.0, Decimal("1.5")), Decimal("17.25"))

    def test_minimum_fare_applies_before_surge(self):
        self.assertEqual(self.fares.fare(0.5, 1.0, Decimal("1.0")), Decimal("5.00"))
        self.assertEqual(self.fares.fare(0.5, 1.0, Decimal("2.0")), Decimal("10.00"))

    def test_negative_inputs_rejected(self):
        with self.assertRaises(InvalidInputError):
            self.fares.fare(-1.0, 1.0, Decimal("1.0"))
        with self.assertRaises(InvalidInputError):
            self.surge.multiplier(demand=-1, supply=0)

    def test_request_locks_in_the_surge_at_request_time(self):
        service, _, _ = make_service()
        add_driver(service, "d1", 0.5, 0.0)
        service.register_rider("r2", "Maya")
        first = service.request_ride("r1", HOME, OFFICE)  # d1 now OFFERED
        second = service.request_ride("r2", HOME, OFFICE)  # demand 2, supply 0
        self.assertEqual(first.surge, Decimal("1.0"))
        self.assertEqual(second.surge, Decimal("2.5"))


class DispatchTests(unittest.TestCase):
    def test_request_offers_the_nearest_driver(self):
        service, _, _ = make_service()
        add_driver(service, "near", 0.5, 0.0)
        add_driver(service, "far", 2.0, 0.0)
        trip = service.request_ride("r1", HOME, OFFICE)
        self.assertEqual(offer_of(service, trip).driver_id, "near")
        self.assertIs(service.get_driver("near").status, DriverStatus.OFFERED)

    def test_decline_reoffers_to_next_driver(self):
        service, _, recorder = make_service()
        add_driver(service, "near", 0.5, 0.0)
        add_driver(service, "far", 2.0, 0.0)
        trip = service.request_ride("r1", HOME, OFFICE)
        service.decline_offer(offer_of(service, trip).offer_id)
        self.assertEqual(offer_of(service, trip).driver_id, "far")
        self.assertIs(service.get_driver("near").status, DriverStatus.AVAILABLE)
        self.assertIn(EventKind.OFFER_DECLINED, recorder.kinds(trip.trip_id))

    def test_timeout_reoffers_and_late_accept_fails(self):
        service, clock, _ = make_service()
        add_driver(service, "near", 0.5, 0.0)
        add_driver(service, "far", 2.0, 0.0)
        trip = service.request_ride("r1", HOME, OFFICE)
        stale = offer_of(service, trip)
        clock.advance(RideConfig().offer_timeout_s)
        self.assertEqual(service.expire_offers(), [trip])
        self.assertEqual(offer_of(service, trip).driver_id, "far")
        with self.assertRaises(OfferNotFoundError):
            service.accept_offer(stale.offer_id)

    def test_accept_after_deadline_raises_expired_and_reoffers(self):
        service, clock, _ = make_service()
        add_driver(service, "near", 0.5, 0.0)
        add_driver(service, "far", 2.0, 0.0)
        trip = service.request_ride("r1", HOME, OFFICE)
        offer = offer_of(service, trip)
        clock.advance(RideConfig().offer_timeout_s + 1)  # sweeper has not run yet
        with self.assertRaises(OfferExpiredError):
            service.accept_offer(offer.offer_id)
        self.assertEqual(offer_of(service, trip).driver_id, "far")

    def test_no_driver_in_radius_cancels_trip(self):
        service, _, _ = make_service()
        add_driver(service, "far", 50.0, 50.0)
        trip = service.request_ride("r1", HOME, OFFICE)
        self.assertIs(trip.status, TripStatus.CANCELLED)
        self.assertIs(trip.cancelled_by, CancelledBy.SYSTEM)
        self.assertEqual(trip.cancellation_fee, Decimal("0.00"))

    def test_max_offer_attempts_then_cancel(self):
        service, _, _ = make_service(RideConfig(max_offer_attempts=2))
        for i in range(3):
            add_driver(service, f"d{i}", 0.1 * (i + 1), 0.0)
        trip = service.request_ride("r1", HOME, OFFICE)
        service.decline_offer(offer_of(service, trip).offer_id)
        service.decline_offer(offer_of(service, trip).offer_id)
        self.assertIs(trip.status, TripStatus.CANCELLED)
        self.assertIs(service.get_driver("d2").status, DriverStatus.AVAILABLE)

    def test_offline_driver_is_never_offered(self):
        service, _, _ = make_service()
        add_driver(service, "sleepy", 0.1, 0.0, online=False)
        add_driver(service, "awake", 2.0, 0.0)
        trip = service.request_ride("r1", HOME, OFFICE)
        self.assertEqual(offer_of(service, trip).driver_id, "awake")

    def test_location_update_changes_who_is_nearest(self):
        service, _, _ = make_service()
        add_driver(service, "a", 0.5, 0.0)
        add_driver(service, "b", 2.0, 0.0)
        service.update_location("b", Location(0.1, 0.0))
        trip = service.request_ride("r1", HOME, OFFICE)
        self.assertEqual(offer_of(service, trip).driver_id, "b")

    def test_busy_driver_cannot_go_offline(self):
        service, _, _ = make_service()
        add_driver(service, "d1", 0.5, 0.0)
        service.request_ride("r1", HOME, OFFICE)
        with self.assertRaises(DriverBusyError):
            service.go_offline("d1")

    def test_each_offer_answers_once(self):
        service, _, _ = make_service()
        trip = matched_trip(service)
        with self.assertRaises(OfferNotFoundError):
            service.decline_offer("O1")
        self.assertIs(trip.status, TripStatus.MATCHED)


class TripFlowTests(unittest.TestCase):
    def test_happy_path_fare_and_events(self):
        service, clock, recorder = make_service()
        trip = matched_trip(service)
        service.driver_arriving(trip.trip_id)
        service.start_trip(trip.trip_id)
        clock.advance(10 * 60)
        service.complete_trip(trip.trip_id)
        self.assertEqual(trip.fare, Decimal("11.50"))  # 5 km, 10 min, 1.0x
        self.assertIs(service.get_driver("d1").status, DriverStatus.AVAILABLE)
        self.assertEqual(service.get_driver("d1").location, OFFICE)
        self.assertEqual(recorder.kinds(trip.trip_id), [
            EventKind.REQUESTED, EventKind.OFFERED, EventKind.MATCHED,
            EventKind.DRIVER_ARRIVING, EventKind.STARTED, EventKind.COMPLETED])

    def test_quote_estimates_from_average_speed(self):
        service, _, _ = make_service()
        add_driver(service, "d1", 0.5, 0.0)
        quote = service.quote(HOME, OFFICE)
        self.assertEqual(quote.estimated_minutes, 10.0)  # 5 km at 30 km/h
        self.assertEqual(quote.estimate, Decimal("11.50"))

    def test_bad_requests_rejected(self):
        service, _, _ = make_service()
        with self.assertRaises(RiderNotFoundError):
            service.request_ride("ghost", HOME, OFFICE)
        with self.assertRaises(InvalidInputError):
            service.request_ride("r1", HOME, HOME)
        with self.assertRaises(InvalidInputError):
            service.register_rider("  ", "Nobody")
        with self.assertRaises(InvalidInputError):
            RideConfig(search_radius_km=0)


class CancellationTests(unittest.TestCase):
    def test_rider_cancels_free_inside_window(self):
        service, clock, _ = make_service()
        trip = matched_trip(service)
        clock.advance(RideConfig().free_cancel_window_s)
        service.cancel_trip(trip.trip_id, CancelledBy.RIDER)
        self.assertEqual(trip.cancellation_fee, Decimal("0.00"))
        self.assertIs(service.get_driver("d1").status, DriverStatus.AVAILABLE)

    def test_rider_pays_fee_after_window(self):
        service, clock, _ = make_service()
        trip = matched_trip(service)
        service.driver_arriving(trip.trip_id)
        clock.advance(RideConfig().free_cancel_window_s + 1)
        service.cancel_trip(trip.trip_id, CancelledBy.RIDER)
        self.assertEqual(trip.cancellation_fee, Decimal("4.00"))

    def test_driver_cancel_never_charges_rider(self):
        service, clock, _ = make_service()
        trip = matched_trip(service)
        clock.advance(600)
        service.cancel_trip(trip.trip_id, CancelledBy.DRIVER)
        self.assertEqual(trip.cancellation_fee, Decimal("0.00"))

    def test_cancel_while_requested_withdraws_the_offer(self):
        service, _, _ = make_service()
        add_driver(service, "d1", 0.5, 0.0)
        trip = service.request_ride("r1", HOME, OFFICE)
        offer = offer_of(service, trip)
        service.cancel_trip(trip.trip_id, CancelledBy.RIDER)
        self.assertIs(service.get_driver("d1").status, DriverStatus.AVAILABLE)
        with self.assertRaises(OfferNotFoundError):
            service.accept_offer(offer.offer_id)

    def test_cannot_cancel_in_progress_or_twice(self):
        service, _, _ = make_service()
        trip = matched_trip(service)
        service.driver_arriving(trip.trip_id)
        service.start_trip(trip.trip_id)
        with self.assertRaises(IllegalTransitionError):
            service.cancel_trip(trip.trip_id, CancelledBy.RIDER)
        self.assertIs(service.get_driver("d1").status, DriverStatus.ON_TRIP)

    def test_policy_ignores_unmatched_trips(self):
        policy = GracePeriodCancellation(RideConfig())
        trip = Trip("T", "r1", HOME, OFFICE, START, Decimal("1.0"))
        fee = policy.fee(trip, CancelledBy.RIDER, START + timedelta(hours=1))
        self.assertEqual(fee, Decimal("0.00"))


class RatingTests(unittest.TestCase):
    def completed(self):
        service, _, _ = make_service()
        trip = matched_trip(service)
        service.driver_arriving(trip.trip_id)
        service.start_trip(trip.trip_id)
        service.complete_trip(trip.trip_id)
        return service, trip

    def test_both_sides_rate_once(self):
        service, trip = self.completed()
        self.assertEqual(service.rate_driver(trip.trip_id, 4), 4.0)
        self.assertEqual(service.rate_rider(trip.trip_id, 5), 5.0)
        with self.assertRaises(RatingError):
            service.rate_driver(trip.trip_id, 5)

    def test_out_of_range_and_non_int_rejected(self):
        service, trip = self.completed()
        for bad in (0, 6, 4.5, True):
            with self.assertRaises(RatingError):
                service.rate_driver(trip.trip_id, bad)

    def test_cannot_rate_unfinished_trip(self):
        service, _, _ = make_service()
        trip = matched_trip(service)
        with self.assertRaises(RatingError):
            service.rate_driver(trip.trip_id, 5)


class ObserverTests(unittest.TestCase):
    def test_failing_observer_does_not_break_dispatch(self):
        class Broken(TripObserver):
            def notify(self, event):
                raise RuntimeError("SMS gateway down")

        service, _, recorder = make_service()
        service.subscribe(Broken())
        add_driver(service, "d1", 0.5, 0.0)
        with self.assertLogs("ride_sharing.events", level="ERROR"):
            trip = service.request_ride("r1", HOME, OFFICE)
        self.assertEqual(recorder.kinds(trip.trip_id),
                         [EventKind.REQUESTED, EventKind.OFFERED])


class ConcurrencyTests(unittest.TestCase):
    def test_concurrent_requests_never_double_assign_a_driver(self):
        service, _, _ = make_service()
        for i in range(4):
            add_driver(service, f"d{i}", 0.1 * i, 0.0)
        for i in range(2, 21):
            service.register_rider(f"r{i}", f"Rider {i}")
        riders = ["r1"] + [f"r{i}" for i in range(2, 21)]
        barrier = threading.Barrier(len(riders))
        trips = []

        def ride(rider_id):
            barrier.wait()
            trips.append(service.request_ride(rider_id, HOME, OFFICE))

        threads = [threading.Thread(target=ride, args=(r,)) for r in riders]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        offered = [offer_of(service, t).driver_id for t in trips
                   if t.status is TripStatus.REQUESTED]
        self.assertEqual(sorted(offered), ["d0", "d1", "d2", "d3"])
        self.assertEqual(sum(t.status is TripStatus.CANCELLED for t in trips), 16)

    def test_same_offer_accepted_twice_has_one_winner(self):
        service, _, _ = make_service()
        add_driver(service, "d1", 0.5, 0.0)
        trip = service.request_ride("r1", HOME, OFFICE)
        offer_id = offer_of(service, trip).offer_id
        barrier = threading.Barrier(2)
        outcomes = []

        def accept():
            barrier.wait()
            try:
                service.accept_offer(offer_id)
                outcomes.append("won")
            except OfferNotFoundError:
                outcomes.append("lost")

        threads = [threading.Thread(target=accept) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(outcomes), ["lost", "won"])
        self.assertIs(trip.status, TripStatus.MATCHED)

    def test_claim_is_atomic_under_contention(self):
        drivers = InMemoryDrivers()
        drivers.add(Driver("d1", "D1", HOME, status=DriverStatus.AVAILABLE))
        barrier = threading.Barrier(16)
        wins = []

        def grab():
            barrier.wait()
            if drivers.claim("d1", DriverStatus.AVAILABLE, DriverStatus.OFFERED):
                wins.append(1)

        threads = [threading.Thread(target=grab) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(wins), 1)


if __name__ == "__main__":
    unittest.main()
