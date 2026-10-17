"""The use-case layer: riders request, drivers answer, trips move.

RideService orchestrates and decides nothing on its own. The dispatcher
picks drivers, the state table judges transitions, the pricing classes do
the money, the publisher tells the world. One RLock serializes the trip
lifecycle; driver claims are additionally atomic in the repository, so
location pings and online/offline toggles never need the service lock.
"""
import itertools
import logging
import threading
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from .clock import Clock, SystemClock
from .config import RideConfig
from .dispatch import Dispatcher
from .errors import DriverBusyError, InvalidInputError, OfferExpiredError, RatingError
from .events import EventKind, EventPublisher, TripEvent, TripObserver
from .lifecycle import transition
from .matching import MatchingStrategy, NearestDriverStrategy
from .models import (
    CancelledBy,
    Driver,
    DriverStatus,
    FareQuote,
    Location,
    Offer,
    Rider,
    Trip,
    TripStatus,
)
from .pricing import (
    CancellationPolicy,
    FareStrategy,
    GracePeriodCancellation,
    StandardFare,
    SupplyDemandSurge,
    SurgePolicy,
)
from .repositories import (
    DriverRepository,
    InMemoryDrivers,
    InMemoryRiders,
    InMemoryTrips,
    RiderRepository,
    TripRepository,
)
from .spatial import GridIndex, SpatialIndex

log = logging.getLogger(__name__)

NO_DRIVER = "no driver available"


def _require_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidInputError(f"{name} must be a non-blank string")
    return value.strip()


class RideService:
    def __init__(
        self,
        *,
        config: RideConfig | None = None,
        clock: Clock | None = None,
        riders: RiderRepository | None = None,
        drivers: DriverRepository | None = None,
        trips: TripRepository | None = None,
        index: SpatialIndex | None = None,
        matching: MatchingStrategy | None = None,
        surge: SurgePolicy | None = None,
        fares: FareStrategy | None = None,
        cancellation: CancellationPolicy | None = None,
        events: EventPublisher | None = None,
    ) -> None:
        self._config = config or RideConfig()
        self._clock = clock or SystemClock()
        self._riders = riders or InMemoryRiders()
        self._drivers = drivers or InMemoryDrivers()
        self._trips = trips or InMemoryTrips()
        self._index = index or GridIndex(self._config.grid_cell_km)
        self._surge = surge or SupplyDemandSurge(self._config)
        self._fares = fares or StandardFare(self._config)
        self._cancellation = cancellation or GracePeriodCancellation(self._config)
        self._events = events or EventPublisher()
        self._dispatcher = Dispatcher(self._drivers, self._index,
                                      matching or NearestDriverStrategy(),
                                      self._clock, self._config)
        self._trip_seq = itertools.count(1)
        # Guards every Trip field, the trip id sequence, and the
        # answer-an-offer sequence (take offer -> move trip -> move driver).
        self._lock = threading.RLock()

    def subscribe(self, observer: TripObserver) -> None:
        self._events.subscribe(observer)

    # -- people ---------------------------------------------------------

    def register_rider(self, rider_id: str, name: str) -> Rider:
        rider = Rider(_require_text(rider_id, "rider_id"), _require_text(name, "name"))
        self._riders.add(rider)
        return rider

    def register_driver(self, driver_id: str, name: str, location: Location) -> Driver:
        driver = Driver(_require_text(driver_id, "driver_id"),
                        _require_text(name, "name"), location)
        self._drivers.add(driver)
        return driver

    def get_driver(self, driver_id: str) -> Driver:
        return self._drivers.get(driver_id)

    def go_online(self, driver_id: str) -> None:
        driver = self._drivers.get(driver_id)
        if driver.status is DriverStatus.AVAILABLE:
            return
        if not self._drivers.claim(driver_id, DriverStatus.OFFLINE, DriverStatus.AVAILABLE):
            raise DriverBusyError(f"{driver_id} is {driver.status.value}")
        self._index.upsert(driver_id, driver.location)
        log.info("%s online at %s", driver_id, driver.location)

    def go_offline(self, driver_id: str) -> None:
        driver = self._drivers.get(driver_id)
        if driver.status is DriverStatus.OFFLINE:
            return
        if not self._drivers.claim(driver_id, DriverStatus.AVAILABLE, DriverStatus.OFFLINE):
            raise DriverBusyError(f"{driver_id} is {driver.status.value}")
        self._index.remove(driver_id)
        log.info("%s offline", driver_id)

    def update_location(self, driver_id: str, location: Location) -> None:
        """The hot path: called every few seconds per driver. No service lock."""
        self._drivers.move(driver_id, location)
        if self._drivers.get(driver_id).status is not DriverStatus.OFFLINE:
            self._index.upsert(driver_id, location)

    # -- pricing --------------------------------------------------------

    def quote(self, pickup: Location, dropoff: Location) -> FareQuote:
        with self._lock:
            surge = self._current_surge(pickup)
        distance = pickup.distance_to(dropoff)
        minutes = distance / self._config.avg_speed_kmh * 60
        return FareQuote(round(distance, 3), round(minutes, 2), surge,
                         self._fares.fare(distance, minutes, surge))

    # -- the ride -------------------------------------------------------

    def request_ride(self, rider_id: str, pickup: Location, dropoff: Location) -> Trip:
        self._riders.get(rider_id)  # unknown rider fails before anything changes
        if pickup == dropoff:
            raise InvalidInputError("pickup and dropoff must differ")
        with self._lock:
            now = self._clock.now()
            trip = Trip(trip_id=f"T{next(self._trip_seq)}", rider_id=rider_id,
                        pickup=pickup, dropoff=dropoff, requested_at=now,
                        surge=self._current_surge(pickup))
            self._trips.add(trip)
            self._publish(EventKind.REQUESTED, trip, detail=f"surge {trip.surge}x")
            self._offer_or_cancel(trip)
            return trip

    def accept_offer(self, offer_id: str) -> Trip:
        with self._lock:
            offer = self._dispatcher.take(offer_id)
            trip = self._trips.get(offer.trip_id)
            if offer.is_expired(self._clock.now()):
                self._release_and_reoffer(offer, trip, EventKind.OFFER_EXPIRED)
                raise OfferExpiredError(f"offer {offer_id} expired at {offer.expires_at}")
            transition(trip, TripStatus.MATCHED)
            self._must_claim(offer.driver_id, DriverStatus.OFFERED, DriverStatus.ON_TRIP)
            trip.driver_id = offer.driver_id
            trip.matched_at = self._clock.now()
            self._publish(EventKind.MATCHED, trip)
            return trip

    def decline_offer(self, offer_id: str) -> Trip:
        with self._lock:
            offer = self._dispatcher.take(offer_id)
            trip = self._trips.get(offer.trip_id)
            self._release_and_reoffer(offer, trip, EventKind.OFFER_DECLINED)
            return trip

    def expire_offers(self) -> list[Trip]:
        """Sweep offers past their deadline; call it from a timer."""
        with self._lock:
            touched = []
            for stale in self._dispatcher.expired(self._clock.now()):
                offer = self._dispatcher.take(stale.offer_id)
                trip = self._trips.get(offer.trip_id)
                self._release_and_reoffer(offer, trip, EventKind.OFFER_EXPIRED)
                touched.append(trip)
            return touched

    def pending_offer(self, trip_id: str) -> Offer | None:
        return self._dispatcher.pending_for(trip_id)

    def driver_arriving(self, trip_id: str) -> Trip:
        with self._lock:
            trip = self._trips.get(trip_id)
            transition(trip, TripStatus.DRIVER_ARRIVING)
            self._publish(EventKind.DRIVER_ARRIVING, trip)
            return trip

    def start_trip(self, trip_id: str) -> Trip:
        with self._lock:
            trip = self._trips.get(trip_id)
            transition(trip, TripStatus.IN_PROGRESS)
            trip.started_at = self._clock.now()
            self._publish(EventKind.STARTED, trip)
            return trip

    def complete_trip(self, trip_id: str) -> Trip:
        with self._lock:
            trip = self._trips.get(trip_id)
            transition(trip, TripStatus.COMPLETED)
            now = self._clock.now()
            trip.completed_at = now
            minutes = (now - trip.started_at).total_seconds() / 60
            trip.fare = self._fares.fare(trip.distance_km, minutes, trip.surge)
            self._drivers.move(trip.driver_id, trip.dropoff)
            self._index.upsert(trip.driver_id, trip.dropoff)
            self._must_claim(trip.driver_id, DriverStatus.ON_TRIP, DriverStatus.AVAILABLE)
            self._publish(EventKind.COMPLETED, trip, detail=f"fare ${trip.fare}")
            return trip

    def cancel_trip(self, trip_id: str, by: CancelledBy, reason: str = "") -> Trip:
        if not isinstance(by, CancelledBy):
            raise InvalidInputError("by must be a CancelledBy")
        with self._lock:
            trip = self._trips.get(trip_id)
            self._cancel(trip, by, reason or f"cancelled by {by.value.lower()}")
            return trip

    def get_trip(self, trip_id: str) -> Trip:
        return self._trips.get(trip_id)

    # -- ratings --------------------------------------------------------

    def rate_driver(self, trip_id: str, stars: int) -> float:
        """The rider rates the driver. Returns the driver's new average."""
        with self._lock:
            trip = self._rateable(trip_id, stars, already=lambda t: t.driver_rated)
            driver = self._drivers.get(trip.driver_id)
            driver.ratings.add(stars)
            trip.driver_rated = True
            return driver.ratings.average(self._config.default_rating)

    def rate_rider(self, trip_id: str, stars: int) -> float:
        """The driver rates the rider. Returns the rider's new average."""
        with self._lock:
            trip = self._rateable(trip_id, stars, already=lambda t: t.rider_rated)
            rider = self._riders.get(trip.rider_id)
            rider.ratings.add(stars)
            trip.rider_rated = True
            return rider.ratings.average(self._config.default_rating)

    # -- internals (caller holds self._lock) -----------------------------

    def _current_surge(self, pickup: Location) -> Decimal:
        radius = self._config.search_radius_km
        waiting = sum(1 for t in self._trips.with_status(TripStatus.REQUESTED)
                      if t.pickup.distance_to(pickup) <= radius)
        supply = len(self._dispatcher.available_near(pickup))
        return self._surge.multiplier(demand=waiting + 1, supply=supply)

    def _offer_or_cancel(self, trip: Trip) -> None:
        offer = self._dispatcher.offer_next(trip)
        if offer is None:
            self._cancel(trip, CancelledBy.SYSTEM, NO_DRIVER)
        else:
            self._publish(EventKind.OFFERED, trip, driver_id=offer.driver_id,
                          detail=f"offer {offer.offer_id}")

    def _release_and_reoffer(self, offer: Offer, trip: Trip, kind: EventKind) -> None:
        self._must_claim(offer.driver_id, DriverStatus.OFFERED, DriverStatus.AVAILABLE)
        trip.declined_driver_ids.add(offer.driver_id)
        self._publish(kind, trip, driver_id=offer.driver_id)
        self._offer_or_cancel(trip)

    def _cancel(self, trip: Trip, by: CancelledBy, reason: str) -> None:
        transition(trip, TripStatus.CANCELLED)  # raises first, before any change
        now = self._clock.now()
        trip.cancellation_fee = self._cancellation.fee(trip, by, now)
        trip.cancelled_at, trip.cancelled_by, trip.cancel_reason = now, by, reason
        pending = self._dispatcher.withdraw(trip.trip_id)
        if pending is not None:
            self._must_claim(pending.driver_id, DriverStatus.OFFERED, DriverStatus.AVAILABLE)
        if trip.driver_id is not None:
            self._must_claim(trip.driver_id, DriverStatus.ON_TRIP, DriverStatus.AVAILABLE)
        self._publish(EventKind.CANCELLED, trip, detail=f"{reason}; fee ${trip.cancellation_fee}")

    def _rateable(self, trip_id: str, stars: int,
                  already: Callable[[Trip], bool]) -> Trip:
        if isinstance(stars, bool) or not isinstance(stars, int) \
                or not 1 <= stars <= self._config.max_stars:
            raise RatingError(f"stars must be an int in 1..{self._config.max_stars}")
        trip = self._trips.get(trip_id)
        if trip.status is not TripStatus.COMPLETED:
            raise RatingError(f"trip {trip_id} is {trip.status}, not COMPLETED")
        if already(trip):
            raise RatingError(f"trip {trip_id} already rated")
        return trip

    def _must_claim(self, driver_id: str, expected: DriverStatus, new: DriverStatus) -> None:
        if not self._drivers.claim(driver_id, expected, new):
            raise DriverBusyError(f"{driver_id} was not {expected.value}")

    def _publish(self, kind: EventKind, trip: Trip, *, driver_id: str | None = None,
                 detail: str = "") -> None:
        at: datetime = self._clock.now()
        event = TripEvent(kind, trip.trip_id, at, driver_id or trip.driver_id, detail)
        log.info("%s %s %s", trip.trip_id, kind.value, detail)
        self._events.publish(event)
