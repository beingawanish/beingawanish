"""Repositories: the catalog (read-mostly) and the bookings (write-heavy).

Two interfaces because they change for different reasons and would live in
different stores in production: the catalog in a cached SQL table, bookings
in the transactional store.
"""
import threading
from abc import ABC, abstractmethod

from .errors import BookingNotFoundError, NotFoundError, ShowNotFoundError
from .models import Booking, Cinema, Movie, Screen, Show


class CatalogRepository(ABC):
    @abstractmethod
    def add_cinema(self, cinema: Cinema) -> None: ...

    @abstractmethod
    def add_screen(self, screen: Screen) -> None: ...

    @abstractmethod
    def add_movie(self, movie: Movie) -> None: ...

    @abstractmethod
    def add_show(self, show: Show) -> None: ...

    @abstractmethod
    def get_cinema(self, cinema_id: str) -> Cinema: ...

    @abstractmethod
    def get_screen(self, screen_id: str) -> Screen: ...

    @abstractmethod
    def get_movie(self, movie_id: str) -> Movie: ...

    @abstractmethod
    def get_show(self, show_id: str) -> Show: ...

    @abstractmethod
    def all_shows(self) -> list[Show]: ...


class InMemoryCatalog(CatalogRepository):
    def __init__(self) -> None:
        self._cinemas: dict[str, Cinema] = {}
        self._screens: dict[str, Screen] = {}
        self._movies: dict[str, Movie] = {}
        self._shows: dict[str, Show] = {}
        self._lock = threading.Lock()  # guards all four dicts

    def add_cinema(self, cinema: Cinema) -> None:
        with self._lock:
            self._cinemas[cinema.cinema_id] = cinema

    def add_screen(self, screen: Screen) -> None:
        with self._lock:
            if screen.cinema_id not in self._cinemas:
                raise NotFoundError(f"unknown cinema {screen.cinema_id}")
            self._screens[screen.screen_id] = screen

    def add_movie(self, movie: Movie) -> None:
        with self._lock:
            self._movies[movie.movie_id] = movie

    def add_show(self, show: Show) -> None:
        with self._lock:
            if show.screen_id not in self._screens:
                raise NotFoundError(f"unknown screen {show.screen_id}")
            if show.movie_id not in self._movies:
                raise NotFoundError(f"unknown movie {show.movie_id}")
            self._shows[show.show_id] = show

    def get_cinema(self, cinema_id: str) -> Cinema:
        with self._lock:
            if cinema_id not in self._cinemas:
                raise NotFoundError(f"unknown cinema {cinema_id}")
            return self._cinemas[cinema_id]

    def get_screen(self, screen_id: str) -> Screen:
        with self._lock:
            if screen_id not in self._screens:
                raise NotFoundError(f"unknown screen {screen_id}")
            return self._screens[screen_id]

    def get_movie(self, movie_id: str) -> Movie:
        with self._lock:
            if movie_id not in self._movies:
                raise NotFoundError(f"unknown movie {movie_id}")
            return self._movies[movie_id]

    def get_show(self, show_id: str) -> Show:
        with self._lock:
            if show_id not in self._shows:
                raise ShowNotFoundError(f"unknown show {show_id}")
            return self._shows[show_id]

    def all_shows(self) -> list[Show]:
        with self._lock:
            return list(self._shows.values())


class BookingRepository(ABC):
    @abstractmethod
    def add(self, booking: Booking) -> None: ...

    @abstractmethod
    def get(self, booking_id: str) -> Booking: ...

    @abstractmethod
    def for_show(self, show_id: str) -> list[Booking]: ...


class InMemoryBookingRepository(BookingRepository):
    def __init__(self) -> None:
        self._bookings: dict[str, Booking] = {}
        self._by_show: dict[str, list[str]] = {}
        self._lock = threading.Lock()  # guards both dicts

    def add(self, booking: Booking) -> None:
        with self._lock:
            self._bookings[booking.booking_id] = booking
            self._by_show.setdefault(booking.show_id, []).append(booking.booking_id)

    def get(self, booking_id: str) -> Booking:
        with self._lock:
            if booking_id not in self._bookings:
                raise BookingNotFoundError(f"unknown booking {booking_id}")
            return self._bookings[booking_id]

    def for_show(self, show_id: str) -> list[Booking]:
        with self._lock:
            return [self._bookings[b] for b in self._by_show.get(show_id, [])]
