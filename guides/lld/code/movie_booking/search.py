"""Show search: the read path. It never takes a show lock and never mutates."""
from dataclasses import dataclass
from datetime import date

from .clock import Clock
from .errors import InvalidRequestError
from .models import Cinema, Movie, Screen, Show
from .repositories import CatalogRepository


@dataclass(frozen=True)
class ShowListing:
    show: Show
    movie: Movie
    cinema: Cinema
    screen: Screen


class ShowSearch:
    def __init__(self, catalog: CatalogRepository, clock: Clock) -> None:
        self._catalog = catalog
        self._clock = clock

    def find(
        self, city: str, *, movie_id: str | None = None, on_date: date | None = None,
    ) -> list[ShowListing]:
        """Upcoming shows in a city, soonest first. Dates are the show's local date."""
        if not city.strip():
            raise InvalidRequestError("city is required")
        now = self._clock.now()
        listings = []
        for show in self._catalog.all_shows():
            if show.starts_at <= now:
                continue
            if movie_id is not None and show.movie_id != movie_id:
                continue
            if on_date is not None and show.starts_at.date() != on_date:
                continue
            screen = self._catalog.get_screen(show.screen_id)
            cinema = self._catalog.get_cinema(screen.cinema_id)
            if cinema.city.casefold() != city.strip().casefold():
                continue
            movie = self._catalog.get_movie(show.movie_id)
            listings.append(ShowListing(show, movie, cinema, screen))
        return sorted(listings, key=lambda listing: listing.show.starts_at)
