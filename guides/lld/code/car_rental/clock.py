"""Injectable clock. Same idea as in the library: domain code never calls
date.today() directly, so tests freeze time with FixedClock."""
from abc import ABC, abstractmethod
from datetime import date, timedelta


class Clock(ABC):
    @abstractmethod
    def today(self) -> date:
        ...


class SystemClock(Clock):
    def today(self) -> date:
        return date.today()


class FixedClock(Clock):
    def __init__(self, today: date):
        self._today = today

    def today(self) -> date:
        return self._today

    def advance(self, days: int) -> None:
        self._today += timedelta(days=days)
