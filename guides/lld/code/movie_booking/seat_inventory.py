"""Seat inventory: who owns which seat of a show, plus one lock per show.

This is the heart of the chapter. Two users click the same seat at the same
instant; exactly one claim may succeed. The rule is enforced in two layers:

* ShowSeatMap.claim is all-or-nothing: it checks every seat, then assigns them.
* SeatInventory hands out one RLock per show, and BookingService performs
  every check-then-claim while holding it. Different shows never contend.
"""
import threading
from collections.abc import Iterable
from dataclasses import dataclass

from .errors import SeatUnavailableError
from .repositories import CatalogRepository


class ShowSeatMap:
    """Seat ownership for one show: seat_id -> booking_id, or None when free.

    Not thread-safe by itself. Callers hold the show's lock.
    """

    def __init__(self, show_id: str, seat_ids: Iterable[str]) -> None:
        self._show_id = show_id
        self._owner: dict[str, str | None] = {seat_id: None for seat_id in seat_ids}

    def owner(self, seat_id: str) -> str | None:
        return self._owner[seat_id]

    def free_seat_ids(self) -> list[str]:
        return [s for s, owner in self._owner.items() if owner is None]

    def claim(self, seat_ids: Iterable[str], booking_id: str) -> None:
        wanted = list(seat_ids)
        taken = [s for s in wanted if self._owner[s] is not None]
        if taken:
            raise SeatUnavailableError(self._show_id, taken)
        for seat_id in wanted:
            self._owner[seat_id] = booking_id

    def release(self, seat_ids: Iterable[str], booking_id: str) -> None:
        """Free only the seats this booking actually owns."""
        for seat_id in seat_ids:
            if self._owner.get(seat_id) == booking_id:
                self._owner[seat_id] = None


@dataclass
class ShowState:
    lock: threading.RLock
    seats: ShowSeatMap


class SeatInventory:
    """Creates each show's state on first use and hands back the same one after."""

    def __init__(self, catalog: CatalogRepository) -> None:
        self._catalog = catalog
        self._states: dict[str, ShowState] = {}
        # Guards _states only. Never held while a show lock is held.
        self._registry_lock = threading.Lock()

    def for_show(self, show_id: str) -> ShowState:
        with self._registry_lock:
            state = self._states.get(show_id)
            if state is None:
                show = self._catalog.get_show(show_id)
                screen = self._catalog.get_screen(show.screen_id)
                state = ShowState(
                    lock=threading.RLock(),
                    seats=ShowSeatMap(show_id, (s.seat_id for s in screen.seats)),
                )
                self._states[show_id] = state
            return state
