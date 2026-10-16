"""ETA as a seam. The service asks "how long?"; the estimator decides.

Today it is distance over speed. Tomorrow it is a model trained on traffic
and kitchen load. Either way the service does not change.
"""
from abc import ABC, abstractmethod
from datetime import timedelta

from .config import EtaConfig
from .models import Location, Restaurant


class EtaEstimator(ABC):
    @abstractmethod
    def estimate(self, restaurant: Restaurant, drop: Location,
                 partner_at: Location | None) -> timedelta:
        ...


class DistanceEtaEstimator(EtaEstimator):
    """The partner rides to the restaurant while the kitchen cooks, so the
    wait at the restaurant is the slower of the two, then the ride to drop."""

    def __init__(self, config: EtaConfig):
        self._config = config

    def _ride_minutes(self, a: Location, b: Location) -> float:
        return a.distance_to(b) / self._config.rider_speed_kmph * 60

    def estimate(self, restaurant: Restaurant, drop: Location,
                 partner_at: Location | None) -> timedelta:
        to_restaurant = (self._ride_minutes(partner_at, restaurant.location)
                         if partner_at is not None else 0.0)
        wait = max(float(restaurant.prep_minutes), to_restaurant)
        ride = self._ride_minutes(restaurant.location, drop)
        return timedelta(minutes=round(wait + ride + self._config.buffer_minutes))
