"""Dispatch: find free drivers near a pickup, claim the best one, offer.

The dispatcher owns the pending-offer table. It asks the spatial index who
is near, the matching strategy who is best, and the driver repository to
claim that driver atomically. If the claim loses a race (the driver just
went offline, or another trip got them), it simply tries the next driver.
"""
import itertools
import logging
import threading
from datetime import datetime, timedelta

from .clock import Clock
from .config import RideConfig
from .errors import OfferNotFoundError
from .matching import MatchingStrategy
from .models import Driver, DriverStatus, Location, Offer, Trip
from .repositories import DriverRepository
from .spatial import SpatialIndex

log = logging.getLogger(__name__)


class Dispatcher:
    def __init__(self, drivers: DriverRepository, index: SpatialIndex,
                 strategy: MatchingStrategy, clock: Clock, config: RideConfig) -> None:
        self._drivers = drivers
        self._index = index
        self._strategy = strategy
        self._clock = clock
        self._config = config
        self._offers: dict[str, Offer] = {}
        self._offer_by_trip: dict[str, str] = {}
        self._seq = itertools.count(1)
        self._lock = threading.Lock()  # guards _offers, _offer_by_trip, _seq

    def available_near(self, location: Location) -> list[Driver]:
        nearby = self._index.within(location, self._config.search_radius_km)
        drivers = (self._drivers.get(driver_id) for driver_id, _ in nearby)
        return [d for d in drivers if d.status is DriverStatus.AVAILABLE]

    def offer_next(self, trip: Trip) -> Offer | None:
        """Claim the best untried driver and offer them the trip, or None."""
        if trip.offer_attempts >= self._config.max_offer_attempts:
            return None
        candidates = [d for d in self.available_near(trip.pickup)
                      if d.driver_id not in trip.declined_driver_ids]
        for driver in self._strategy.rank(trip.pickup, candidates):
            if not self._drivers.claim(driver.driver_id,
                                       DriverStatus.AVAILABLE, DriverStatus.OFFERED):
                log.debug("lost claim on %s; trying next", driver.driver_id)
                continue
            offer = self._record(trip.trip_id, driver.driver_id, self._clock.now())
            trip.offer_attempts += 1
            log.info("offered %s to %s (attempt %d)", trip.trip_id,
                     driver.driver_id, trip.offer_attempts)
            return offer
        return None

    def take(self, offer_id: str) -> Offer:
        """Remove and return a pending offer. Each offer can be taken once."""
        with self._lock:
            offer = self._offers.pop(offer_id, None)
            if offer is None:
                raise OfferNotFoundError(f"no pending offer {offer_id}")
            del self._offer_by_trip[offer.trip_id]
            return offer

    def withdraw(self, trip_id: str) -> Offer | None:
        with self._lock:
            offer_id = self._offer_by_trip.pop(trip_id, None)
            return None if offer_id is None else self._offers.pop(offer_id)

    def pending_for(self, trip_id: str) -> Offer | None:
        with self._lock:
            offer_id = self._offer_by_trip.get(trip_id)
            return None if offer_id is None else self._offers[offer_id]

    def expired(self, now: datetime) -> list[Offer]:
        with self._lock:
            return sorted((o for o in self._offers.values() if o.is_expired(now)),
                          key=lambda o: (o.expires_at, o.offer_id))

    def _record(self, trip_id: str, driver_id: str, now: datetime) -> Offer:
        with self._lock:
            offer = Offer(offer_id=f"O{next(self._seq)}", trip_id=trip_id,
                          driver_id=driver_id,
                          expires_at=now + timedelta(seconds=self._config.offer_timeout_s))
            self._offers[offer.offer_id] = offer
            self._offer_by_trip[trip_id] = offer.offer_id
            return offer
