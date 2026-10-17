"""Matching strategies: given a pickup and some free drivers, who goes first?

A strategy only ranks. It never claims a driver or touches a trip, so a new
ranking rule is a new class and nothing else changes.
"""
from abc import ABC, abstractmethod
from collections.abc import Sequence

from .config import RideConfig
from .models import Driver, Location


class MatchingStrategy(ABC):
    @abstractmethod
    def rank(self, pickup: Location, candidates: Sequence[Driver]) -> list[Driver]:
        """Best candidate first. Must be deterministic for equal inputs."""


class NearestDriverStrategy(MatchingStrategy):
    def rank(self, pickup: Location, candidates: Sequence[Driver]) -> list[Driver]:
        return sorted(candidates,
                      key=lambda d: (pickup.distance_to(d.location), d.driver_id))


class RatingWeightedStrategy(MatchingStrategy):
    """Score = distance + penalty per star below the maximum. Lowest wins.

    With the default 0.5 km per star, a 5.0 driver 1.4 km away beats a 4.0
    driver 1.0 km away (1.4 < 1.0 + 0.5).
    """

    def __init__(self, config: RideConfig) -> None:
        self._config = config

    def score(self, pickup: Location, driver: Driver) -> float:
        rating = driver.ratings.average(self._config.default_rating)
        missing_stars = self._config.max_stars - rating
        return (pickup.distance_to(driver.location)
                + self._config.rating_penalty_km_per_star * missing_stars)

    def rank(self, pickup: Location, candidates: Sequence[Driver]) -> list[Driver]:
        return sorted(candidates, key=lambda d: (self.score(pickup, d), d.driver_id))
