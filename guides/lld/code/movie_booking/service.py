"""BookingService: hold seats, confirm with payment, cancel with refund, expire holds.

Locking rules, stated once:

* Every read-check-write on a show's seats or bookings happens under that
  show's RLock (SeatInventory.for_show(...).lock). Shows never block each other.
* No lock is held while the payment gateway is called. A slow gateway must not
  freeze a whole show's seat map. confirm() therefore runs in three phases:
  check under the lock, charge outside it, re-check and commit under it again.
* _keys_lock guards only the idempotency-key map and is never held while
  waiting for any other lock.
"""
import logging
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from .clock import Clock, SystemClock
from .config import BookingConfig, SeatType
from .errors import (
    HoldExpiredError,
    IdempotencyConflictError,
    InvalidRequestError,
    InvalidSeatSelectionError,
    InvalidTransitionError,
    ShowClosedError,
)
from .models import Booking, BookingStatus, Screen, Seat, Show
from .payments import PaymentGateway
from .policies import PricingStrategy, RefundPolicy, SeatTypePricing, TieredRefundPolicy
from .repositories import BookingRepository, CatalogRepository
from .seat_inventory import SeatInventory, ShowState

log = logging.getLogger(__name__)


def _random_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass(frozen=True)
class SeatOffer:
    seat_id: str
    seat_type: SeatType
    price: Decimal


class BookingService:
    def __init__(
        self,
        catalog: CatalogRepository,
        bookings: BookingRepository,
        gateway: PaymentGateway,
        *,
        config: BookingConfig | None = None,
        clock: Clock | None = None,
        pricing: PricingStrategy | None = None,
        refund_policy: RefundPolicy | None = None,
        inventory: SeatInventory | None = None,
        id_factory: Callable[[], str] = _random_id,
    ) -> None:
        self._catalog = catalog
        self._bookings = bookings
        self._gateway = gateway
        self._config = config or BookingConfig()
        self._clock = clock or SystemClock()
        self._pricing = pricing or SeatTypePricing(self._config)
        self._refunds = refund_policy or TieredRefundPolicy(self._config)
        self._inventory = inventory or SeatInventory(catalog)
        self._new_id = id_factory
        self._keys: dict[str, str] = {}  # idempotency key -> booking_id
        self._keys_lock = threading.Lock()  # guards _keys only

    # ---- reads -------------------------------------------------------

    def available_seats(self, show_id: str) -> list[SeatOffer]:
        show = self._catalog.get_show(show_id)
        screen = self._catalog.get_screen(show.screen_id)
        state = self._inventory.for_show(show_id)
        with state.lock:
            self._expire_locked(show_id, state)
            free = state.seats.free_seat_ids()
        return [
            SeatOffer(seat.seat_id, seat.seat_type, self._pricing.price(show, seat))
            for seat in (screen.seat(s) for s in free) if seat is not None
        ]

    # ---- hold --------------------------------------------------------

    def hold_seats(self, show_id: str, user_id: str, seat_ids: Sequence[str]) -> Booking:
        if not user_id.strip():
            raise InvalidRequestError("user_id is required")
        show = self._catalog.get_show(show_id)
        screen = self._catalog.get_screen(show.screen_id)
        seats = self._validate_selection(screen, seat_ids)
        amount = sum((self._pricing.price(show, s) for s in seats), Decimal("0.00"))
        state = self._inventory.for_show(show_id)
        with state.lock:
            now = self._clock.now()
            if now >= show.starts_at:
                raise ShowClosedError(f"show {show_id} has already started")
            self._expire_locked(show_id, state)
            booking = Booking(
                booking_id=self._new_id(),
                show_id=show_id,
                user_id=user_id,
                seat_ids=tuple(seat_ids),
                amount=amount,
                held_until=now + self._config.hold_duration,
            )
            state.seats.claim(booking.seat_ids, booking.booking_id)
            self._bookings.add(booking)
        log.info("held %s for %s on %s (booking %s)",
                 ",".join(booking.seat_ids), user_id, show_id, booking.booking_id)
        return booking

    # ---- confirm -----------------------------------------------------

    def confirm(self, booking_id: str, idempotency_key: str) -> Booking:
        if not idempotency_key.strip():
            raise InvalidRequestError("idempotency_key is required")
        booking = self._bookings.get(booking_id)
        self._bind_key(idempotency_key, booking_id)
        state = self._inventory.for_show(booking.show_id)

        # Phase 1, under the lock: is there still a live hold to pay for?
        with state.lock:
            if booking.status is BookingStatus.CONFIRMED:
                if booking.idempotency_key == idempotency_key:
                    return booking  # a retry of a confirm that already worked
                raise InvalidTransitionError(f"booking {booking_id} is already confirmed")
            if booking.is_hold_expired(self._clock.now()):
                self._expire_one_locked(booking, state)
            if booking.status is BookingStatus.EXPIRED:
                raise HoldExpiredError(f"hold on booking {booking_id} has expired")
            if booking.status is not BookingStatus.HELD:
                raise InvalidTransitionError(
                    f"booking {booking_id} is {booking.status.name}, cannot confirm"
                )
            amount, user_id = booking.amount, booking.user_id

        # Phase 2, no lock: the slow network call. Declines propagate; the hold survives.
        receipt = self._gateway.charge(
            idempotency_key=idempotency_key, user_id=user_id, amount=amount,
        )

        # Phase 3, under the lock: commit only if the seats are still ours.
        with state.lock:
            if booking.status is BookingStatus.HELD:
                booking.transition_to(BookingStatus.CONFIRMED)
                booking.payment_id = receipt.payment_id
                booking.idempotency_key = idempotency_key
                log.info("confirmed booking %s with %s", booking_id, receipt.payment_id)
                return booking
            if booking.payment_id == receipt.payment_id:
                return booking  # a concurrent retry with the same key got here first
            lost_to = booking.status

        # The hold ended while we were charging. Give the money back, then say so.
        self._gateway.refund(
            idempotency_key=f"auto-refund-{idempotency_key}",
            payment_id=receipt.payment_id, amount=receipt.amount,
        )
        log.warning("booking %s became %s during payment; refunded %s",
                    booking_id, lost_to.name, receipt.payment_id)
        error = InvalidTransitionError if lost_to is BookingStatus.CONFIRMED else HoldExpiredError
        raise error(f"booking {booking_id} became {lost_to.name} during payment; charge refunded")

    # ---- cancel ------------------------------------------------------

    def cancel(self, booking_id: str) -> Booking:
        booking = self._bookings.get(booking_id)
        show = self._catalog.get_show(booking.show_id)
        state = self._inventory.for_show(booking.show_id)
        with state.lock:
            now = self._clock.now()
            self._expire_locked(booking.show_id, state)
            was_confirmed = booking.status is BookingStatus.CONFIRMED
            if was_confirmed and now >= show.starts_at:
                raise ShowClosedError(f"show {show.show_id} has started; cannot cancel")
            refund = (self._refunds.refund_for(booking, show, now)
                      if was_confirmed else Decimal("0.00"))
            booking.transition_to(BookingStatus.CANCELLED)  # raises for EXPIRED/CANCELLED
            booking.refund_amount = refund
            state.seats.release(booking.seat_ids, booking.booking_id)
            payment_id = booking.payment_id
        if was_confirmed and refund > 0 and payment_id is not None:
            self._gateway.refund(
                idempotency_key=f"refund-{booking_id}", payment_id=payment_id, amount=refund,
            )
        log.info("cancelled booking %s, refund %s", booking_id, refund)
        return booking

    # ---- expiry ------------------------------------------------------

    def expire_holds(self, show_id: str | None = None) -> int:
        """Sweep expired holds. A background job calls this; reads call it lazily too."""
        show_ids = [show_id] if show_id else [s.show_id for s in self._catalog.all_shows()]
        expired = 0
        for sid in show_ids:
            state = self._inventory.for_show(sid)
            with state.lock:
                expired += self._expire_locked(sid, state)
        return expired

    # ---- helpers (callers hold the show lock where the name says _locked) --

    def _expire_locked(self, show_id: str, state: ShowState) -> int:
        now = self._clock.now()
        count = 0
        for booking in self._bookings.for_show(show_id):
            if booking.is_hold_expired(now):
                self._expire_one_locked(booking, state)
                count += 1
        return count

    def _expire_one_locked(self, booking: Booking, state: ShowState) -> None:
        booking.transition_to(BookingStatus.EXPIRED)
        state.seats.release(booking.seat_ids, booking.booking_id)
        log.info("hold expired: booking %s released %s",
                 booking.booking_id, ",".join(booking.seat_ids))

    def _bind_key(self, key: str, booking_id: str) -> None:
        with self._keys_lock:
            bound = self._keys.setdefault(key, booking_id)
        if bound != booking_id:
            raise IdempotencyConflictError(f"key {key} already used for booking {bound}")

    def _validate_selection(self, screen: Screen, seat_ids: Sequence[str]) -> list[Seat]:
        if isinstance(seat_ids, str) or not seat_ids:
            raise InvalidSeatSelectionError("pick at least one seat, as a list of ids")
        if len(set(seat_ids)) != len(seat_ids):
            raise InvalidSeatSelectionError(f"duplicate seats in {list(seat_ids)}")
        limit = self._config.max_seats_per_booking
        if len(seat_ids) > limit:
            raise InvalidSeatSelectionError(f"at most {limit} seats per booking")
        seats = [screen.seat(s) for s in seat_ids]
        unknown = [s for s, seat in zip(seat_ids, seats) if seat is None]
        if unknown:
            raise InvalidSeatSelectionError(f"no such seats on {screen.name}: {unknown}")
        return [s for s in seats if s is not None]
