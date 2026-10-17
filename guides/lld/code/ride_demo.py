"""Runnable slice: decline, timeout, re-offer, a full trip, surge, a fee.

A ManualClock drives every timestamp, so the output is the same on every run.
"""
from datetime import UTC, datetime

from ride_sharing import (
    CancelledBy,
    IllegalTransitionError,
    Location,
    ManualClock,
    RatingBook,
    RatingWeightedStrategy,
    RideConfig,
    RideService,
    TripEvent,
    TripObserver,
)


class PrintingObserver(TripObserver):
    def notify(self, event: TripEvent) -> None:
        who = f" {event.driver_id}" if event.driver_id else ""
        extra = f" ({event.detail})" if event.detail else ""
        print(f"  [{event.trip_id}] {event.kind.value}{who}{extra}")


def main() -> None:
    config = RideConfig()
    clock = ManualClock(datetime(2026, 10, 16, 18, 0, tzinfo=UTC))
    service = RideService(config=config, clock=clock,
                          matching=RatingWeightedStrategy(config))
    service.subscribe(PrintingObserver())

    drivers = [("asha", "Asha", Location(1.0, 1.0), RatingBook(38, 10)),
               ("ben", "Ben", Location(1.5, 1.0), RatingBook()),
               ("dev", "Dev", Location(2.0, 2.5), RatingBook(46, 10)),
               ("chen", "Chen", Location(8.0, 8.0), RatingBook()),
               ("eve", "Eve", Location(8.5, 8.0), RatingBook())]
    for driver_id, name, where, history in drivers:
        service.register_driver(driver_id, name, where).ratings = history
        service.go_online(driver_id)
    for rider_id, name in [("r1", "Awanish"), ("r2", "Maya"), ("r3", "Omar")]:
        service.register_rider(rider_id, name)

    print("1. Awanish requests a ride: Ben declines, Asha times out")
    trip = service.request_ride("r1", Location(1.0, 1.0), Location(6.0, 5.0))
    service.decline_offer(service.pending_offer(trip.trip_id).offer_id)
    clock.advance(config.offer_timeout_s + 1)
    service.expire_offers()
    service.accept_offer(service.pending_offer(trip.trip_id).offer_id)

    print("2. Dev drives the trip")
    service.driver_arriving(trip.trip_id)
    clock.advance(4 * 60)
    service.start_trip(trip.trip_id)
    clock.advance(14 * 60)
    service.complete_trip(trip.trip_id)
    print(f"  Dev's rating after 5 stars: {service.rate_driver(trip.trip_id, 5):.2f}")

    print("3. Surge: two riders, two drivers, one already busy")
    first = service.request_ride("r2", Location(8.0, 8.0), Location(9.0, 12.0))
    quote = service.quote(Location(8.0, 8.0), Location(9.0, 12.0))
    print(f"  quote now: {quote.surge}x, about ${quote.estimate}")
    service.request_ride("r3", Location(8.0, 8.0), Location(9.0, 12.0))

    print("4. Maya cancels three minutes after Chen accepts")
    service.accept_offer(service.pending_offer(first.trip_id).offer_id)
    clock.advance(3 * 60)
    service.cancel_trip(first.trip_id, CancelledBy.RIDER)

    print("5. The state machine refuses to restart a finished trip")
    try:
        service.start_trip(trip.trip_id)
    except IllegalTransitionError as error:
        print(f"  expected: {error}")


if __name__ == "__main__":
    main()
