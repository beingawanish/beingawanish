"""Runnable slice: search, a seat race, payment with a retried key, expiry, refund.

Run with: python3 -m movie_booking
"""
import itertools
from datetime import datetime, timedelta, timezone

from . import (
    BookingService,
    BookingStatus,
    Cinema,
    FakePaymentGateway,
    FixedClock,
    HoldExpiredError,
    InMemoryBookingRepository,
    InMemoryCatalog,
    Movie,
    Screen,
    SeatType,
    SeatUnavailableError,
    Show,
    ShowSearch,
)

IST = timezone(timedelta(hours=5, minutes=30), "IST")


def main() -> None:
    clock = FixedClock(datetime(2026, 11, 20, 10, 0, tzinfo=IST))
    catalog = InMemoryCatalog()
    catalog.add_cinema(Cinema("LKS-WF", "Lakeside Cinemas Whitefield", "Bengaluru"))
    catalog.add_screen(Screen.from_rows("LKS-3", "LKS-WF", "Audi 3", [
        ("A", 6, SeatType.REGULAR), ("B", 6, SeatType.PREMIUM), ("C", 4, SeatType.RECLINER),
    ]))
    catalog.add_movie(Movie("M-MONSOON", "The Last Monsoon", 148))
    catalog.add_show(Show("S-1900", "M-MONSOON", "LKS-3", datetime(2026, 11, 20, 19, 0, tzinfo=IST)))
    catalog.add_show(Show("S-2230", "M-MONSOON", "LKS-3", datetime(2026, 11, 20, 22, 30, tzinfo=IST)))

    gateway = FakePaymentGateway()
    counter = itertools.count(1)
    service = BookingService(catalog, InMemoryBookingRepository(), gateway,
                             clock=clock, id_factory=lambda: f"BK{next(counter)}")

    for listing in ShowSearch(catalog, clock).find("bengaluru", movie_id="M-MONSOON"):
        print(f"{listing.show.starts_at:%H:%M} {listing.movie.title} at {listing.cinema.name}")
    print("free seats for S-1900:", len(service.available_seats("S-1900")))

    asha = service.hold_seats("S-1900", "asha", ["B1", "B2"])
    print(f"asha holds B1,B2 as {asha.booking_id}: {asha.amount} until {asha.held_until:%H:%M}")
    try:
        service.hold_seats("S-1900", "ravi", ["B2", "B3"])
    except SeatUnavailableError as e:
        print("ravi loses the race:", e)
    ravi = service.hold_seats("S-1900", "ravi", ["B3", "B4"])
    print(f"ravi holds B3,B4 as {ravi.booking_id}")

    service.confirm(asha.booking_id, "asha-checkout-1")
    service.confirm(asha.booking_id, "asha-checkout-1")  # double-click on "Pay"
    print(f"asha {asha.status.name} with {asha.payment_id}; gateway charges: {gateway.charge_count}")

    clock.advance(timedelta(minutes=11))
    meera = service.hold_seats("S-1900", "meera", ["B3"])
    print(f"11 minutes later meera holds B3 as {meera.booking_id}; ravi is {ravi.status.name}")
    try:
        service.confirm(ravi.booking_id, "ravi-checkout-1")
    except HoldExpiredError as e:
        print("ravi pays too late:", e)

    service.cancel(asha.booking_id)
    assert asha.status is BookingStatus.CANCELLED
    print(f"asha cancels 8h49m before the show: refund {asha.refund_amount} of {asha.amount}")


if __name__ == "__main__":
    main()
