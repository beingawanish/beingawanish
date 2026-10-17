"""Domain models: the catalog (cinema, screen, seat, movie, show) and the Booking.

Catalog objects are frozen: a screen's layout does not change under a live show.
Booking is the one mutable model, and it guards its own state machine.
"""
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from .config import SeatType
from .errors import InvalidRequestError, InvalidTransitionError


@dataclass(frozen=True)
class Cinema:
    cinema_id: str
    name: str
    city: str


@dataclass(frozen=True)
class Seat:
    seat_id: str
    seat_type: SeatType


@dataclass(frozen=True)
class Screen:
    screen_id: str
    cinema_id: str
    name: str
    seats: tuple[Seat, ...]
    _index: dict[str, Seat] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.seats:
            raise InvalidRequestError(f"screen {self.screen_id} has no seats")
        index = {s.seat_id: s for s in self.seats}
        if len(index) != len(self.seats):
            raise InvalidRequestError(f"screen {self.screen_id} has duplicate seat ids")
        object.__setattr__(self, "_index", index)

    def seat(self, seat_id: str) -> Seat | None:
        return self._index.get(seat_id)

    @classmethod
    def from_rows(
        cls, screen_id: str, cinema_id: str, name: str,
        rows: Sequence[tuple[str, int, SeatType]],
    ) -> "Screen":
        """Build a layout from (row letter, seats in row, seat type) triples."""
        seats = tuple(
            Seat(f"{row}{n}", seat_type)
            for row, count, seat_type in rows
            for n in range(1, count + 1)
        )
        return cls(screen_id, cinema_id, name, seats)


@dataclass(frozen=True)
class Movie:
    movie_id: str
    title: str
    duration_minutes: int


@dataclass(frozen=True)
class Show:
    show_id: str
    movie_id: str
    screen_id: str
    starts_at: datetime

    def __post_init__(self) -> None:
        if self.starts_at.tzinfo is None:
            raise InvalidRequestError("show times must be timezone-aware")


class BookingStatus(Enum):
    HELD = "held"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


# The whole state machine, in one table. EXPIRED and CANCELLED are terminal.
ALLOWED_TRANSITIONS: dict[BookingStatus, frozenset[BookingStatus]] = {
    BookingStatus.HELD: frozenset({
        BookingStatus.CONFIRMED, BookingStatus.EXPIRED, BookingStatus.CANCELLED,
    }),
    BookingStatus.CONFIRMED: frozenset({BookingStatus.CANCELLED}),
    BookingStatus.EXPIRED: frozenset(),
    BookingStatus.CANCELLED: frozenset(),
}


@dataclass
class Booking:
    """One user's seats for one show.

    Mutated only by BookingService while it holds that show's lock.
    """

    booking_id: str
    show_id: str
    user_id: str
    seat_ids: tuple[str, ...]
    amount: Decimal
    held_until: datetime
    status: BookingStatus = BookingStatus.HELD
    payment_id: str | None = None
    idempotency_key: str | None = None
    refund_amount: Decimal = Decimal("0.00")

    def transition_to(self, new_status: BookingStatus) -> None:
        if new_status not in ALLOWED_TRANSITIONS[self.status]:
            raise InvalidTransitionError(
                f"booking {self.booking_id}: {self.status.name} -> {new_status.name} not allowed"
            )
        self.status = new_status

    def is_hold_expired(self, now: datetime) -> bool:
        return self.status is BookingStatus.HELD and now >= self.held_until
