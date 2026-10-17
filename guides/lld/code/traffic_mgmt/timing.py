"""Timing plans (Strategy): how long each axis stays green in the next cycle.

The controller asks its plan once per cycle, at the instant north-south
green begins. A plan sees a CycleContext (time, detector counts, capacity)
and answers with a GreenSplit. It never touches yellow or all-red: those
belong to SafetyTimings and the controller, so no plan can make a junction
unsafe. That is what lets any plan substitute for any other.
"""
import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from .config import SECONDS_PER_DAY, AdaptiveTuning, SafetyTimings
from .errors import InvalidPlanError
from .models import Axis, GreenSplit


@dataclass(frozen=True)
class CycleContext:
    now: int
    queue_ns: int
    queue_ew: int
    capacity_ns: Fraction = Fraction(1)
    capacity_ew: Fraction = Fraction(1)

    def queue(self, axis: Axis) -> int:
        return self.queue_ns if axis is Axis.NS else self.queue_ew

    def capacity(self, axis: Axis) -> Fraction:
        return self.capacity_ns if axis is Axis.NS else self.capacity_ew


class TimingStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def split(self, ctx: CycleContext) -> GreenSplit:
        """Green seconds for each axis in the cycle starting at ctx.now."""


class FixedTimePlan(TimingStrategy):
    """The same split every cycle. Also the safe local fallback."""

    def __init__(self, ns_green: int, ew_green: int, name: str = "fixed") -> None:
        self._split = GreenSplit(ns_green, ew_green, name)  # validates
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def split(self, ctx: CycleContext) -> GreenSplit:
        return self._split


class AdaptivePlan(TimingStrategy):
    """Green grows with the queue: base + seconds_per_vehicle * queue / capacity.

    Dividing by capacity means a lane closure (capacity 1/2) asks for twice
    the green to clear the same queue. The result is capped at max_green so
    one approach can never starve the other.
    """

    def __init__(self, tuning: AdaptiveTuning, name: str = "adaptive") -> None:
        self._tuning = tuning
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def _green(self, ctx: CycleContext, axis: Axis) -> int:
        t = self._tuning
        needed = t.seconds_per_vehicle * ctx.queue(axis) / ctx.capacity(axis)
        return min(t.max_green, t.base_green + math.ceil(needed))

    def split(self, ctx: CycleContext) -> GreenSplit:
        return GreenSplit(self._green(ctx, Axis.NS), self._green(ctx, Axis.EW), self._name)


class TimeOfDayPlan(TimingStrategy):
    """Picks a sub-plan by time of day: e.g. peak adaptive, night fixed.

    entries are (start_second_of_day, plan), sorted by start. Before the first
    start, the last entry is still in force from the previous evening.
    """

    def __init__(self, entries: Sequence[tuple[int, TimingStrategy]], name: str = "time-of-day") -> None:
        if not entries:
            raise InvalidPlanError("a time-of-day plan needs at least one entry")
        starts = [start for start, _ in entries]
        if starts != sorted(set(starts)):
            raise InvalidPlanError("entry start times must be unique and ascending")
        if starts[0] < 0 or starts[-1] >= SECONDS_PER_DAY:
            raise InvalidPlanError("entry start times must fall within one day")
        self._entries = tuple(entries)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def plan_at(self, now: int) -> TimingStrategy:
        second_of_day = now % SECONDS_PER_DAY
        active = self._entries[-1][1]  # wraps from yesterday
        for start, plan in self._entries:
            if start <= second_of_day:
                active = plan
        return active

    def split(self, ctx: CycleContext) -> GreenSplit:
        return self.plan_at(ctx.now).split(ctx)


class CoordinatedPlan(TimingStrategy):
    """A fixed cycle locked to a city-wide time base: the green-wave building block.

    North-south green starts whenever (now - offset) % cycle_length == 0.
    If a cycle starts off-beat (power-up, plan change, after a preemption),
    this plan stretches or shrinks the east-west green of that one cycle so
    the next one lands exactly on the beat. Then every later cycle is normal.
    """

    def __init__(
        self,
        cycle_length: int,
        offset: int,
        ns_green: int,
        safety: SafetyTimings,
        name: str = "coordinated",
    ) -> None:
        self._overhead = 2 * safety.clearance  # two handovers per cycle
        self._min_green = safety.min_green
        if ns_green < safety.min_green:
            raise InvalidPlanError("ns_green is below the safety minimum")
        if cycle_length < ns_green + safety.min_green + self._overhead:
            raise InvalidPlanError(
                f"cycle {cycle_length}s cannot fit ns_green={ns_green}, a minimum "
                f"cross green and {self._overhead}s of clearance"
            )
        if not 0 <= offset < cycle_length:
            raise InvalidPlanError("offset must be in [0, cycle_length)")
        self.cycle_length = cycle_length
        self.offset = offset
        self.ns_green = ns_green
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def split(self, ctx: CycleContext) -> GreenSplit:
        drift = (ctx.now - self.offset) % self.cycle_length
        length = self.cycle_length - drift  # seconds until the next beat
        if length < self.ns_green + self._min_green + self._overhead:
            length += self.cycle_length  # too short to be safe: aim for the beat after
        ew_green = length - self.ns_green - self._overhead
        return GreenSplit(self.ns_green, ew_green, self._name)
