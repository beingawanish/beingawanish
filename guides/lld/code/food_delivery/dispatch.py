"""Dispatch: offer an order to a delivery partner, and re-offer on timeout.

The strategy answers "which partner?". The dispatcher owns the offer's life:
reserve a partner, wait for an answer, and on decline or timeout release
them and try the next one. After max_offer_attempts it gives up and
reports FAILED; the service decides what failure means for the order.

Lock order: the service lock, then this lock, then the partner repo's lock.
The dispatcher never calls back into the service, so it cannot deadlock.
"""
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .clock import Clock
from .config import DispatchConfig
from .errors import NoActiveOfferError, PartnerMismatchError
from .models import DeliveryPartner, Location
from .repositories import PartnerRepository

log = logging.getLogger(__name__)


class AssignmentStrategy(ABC):
    @abstractmethod
    def choose(self, pickup: Location,
               candidates: Sequence[DeliveryPartner]) -> DeliveryPartner | None:
        ...


class NearestPartnerStrategy(AssignmentStrategy):
    """Closest free partner within the radius. Ties go to the lower id, so
    the choice is deterministic and the tests can pin it."""

    def __init__(self, max_radius_km: float):
        self._max_radius_km = max_radius_km

    def choose(self, pickup: Location,
               candidates: Sequence[DeliveryPartner]) -> DeliveryPartner | None:
        in_range = [p for p in candidates
                    if p.location.distance_to(pickup) <= self._max_radius_km]
        if not in_range:
            return None
        return min(in_range,
                   key=lambda p: (p.location.distance_to(pickup), p.partner_id))


class DispatchResult(Enum):
    OFFERED = "offered"      # a partner holds the offer and must answer
    WAITING = "waiting"      # nobody free in range; retry after the timeout
    FAILED = "failed"        # attempts exhausted; the order needs a decision


@dataclass(frozen=True)
class DispatchOutcome:
    order_id: str
    result: DispatchResult
    partner_id: str | None
    attempt: int


@dataclass
class _Offer:
    order_id: str
    pickup: Location
    partner_id: str | None = None
    offered_at: datetime | None = None
    attempts: int = 0
    accepted: bool = False
    tried: set[str] = field(default_factory=set)


class Dispatcher:
    def __init__(self, partners: PartnerRepository, strategy: AssignmentStrategy,
                 clock: Clock, config: DispatchConfig):
        self._partners = partners
        self._strategy = strategy
        self._clock = clock
        self._config = config
        self._lock = threading.Lock()          # guards _offers
        self._offers: dict[str, _Offer] = {}

    def start(self, order_id: str, pickup: Location) -> DispatchOutcome:
        with self._lock:
            offer = _Offer(order_id=order_id, pickup=pickup)
            self._offers[order_id] = offer
            return self._next_offer(offer)

    def accept(self, order_id: str, partner_id: str) -> None:
        with self._lock:
            offer = self._pending_offer_for(order_id, partner_id)
            offer.accepted = True
            log.info("partner %s accepted %s", partner_id, order_id)

    def decline(self, order_id: str, partner_id: str) -> DispatchOutcome:
        with self._lock:
            offer = self._pending_offer_for(order_id, partner_id)
            log.info("partner %s declined %s", partner_id, order_id)
            return self._next_offer(offer)

    def expire_stale(self) -> list[DispatchOutcome]:
        """Re-offer every unanswered offer older than the timeout."""
        now = self._clock.now()
        outcomes = []
        with self._lock:
            for offer in list(self._offers.values()):
                if offer.accepted or offer.offered_at is None:
                    continue
                if now - offer.offered_at >= self._config.offer_timeout:
                    log.info("offer for %s timed out (partner %s)",
                             offer.order_id, offer.partner_id)
                    outcomes.append(self._next_offer(offer))
        return outcomes

    def finish(self, order_id: str) -> None:
        """Delivered or cancelled: free the partner and forget the offer."""
        with self._lock:
            offer = self._offers.pop(order_id, None)
            if offer is not None and offer.partner_id is not None:
                self._partners.release(offer.partner_id)

    def assigned_partner(self, order_id: str) -> str | None:
        with self._lock:
            offer = self._offers.get(order_id)
            return offer.partner_id if offer and offer.accepted else None

    # -- helpers (caller holds self._lock) ------------------------------

    def _pending_offer_for(self, order_id: str, partner_id: str) -> _Offer:
        offer = self._offers.get(order_id)
        if offer is None or offer.accepted:
            raise NoActiveOfferError(f"no open offer for {order_id}")
        if offer.partner_id != partner_id:
            raise PartnerMismatchError(
                f"{order_id} is offered to {offer.partner_id}, not {partner_id}")
        return offer

    def _next_offer(self, offer: _Offer) -> DispatchOutcome:
        if offer.partner_id is not None:
            self._partners.release(offer.partner_id)
            offer.tried.add(offer.partner_id)
            offer.partner_id = None
        offer.attempts += 1
        if offer.attempts > self._config.max_offer_attempts:
            del self._offers[offer.order_id]
            log.warning("dispatch failed for %s after %d attempts",
                        offer.order_id, offer.attempts - 1)
            return DispatchOutcome(offer.order_id, DispatchResult.FAILED,
                                   None, offer.attempts - 1)
        offer.partner_id = self._claim_partner(offer)
        offer.offered_at = self._clock.now()
        result = (DispatchResult.OFFERED if offer.partner_id
                  else DispatchResult.WAITING)
        log.info("dispatch %s attempt %d: %s %s", offer.order_id,
                 offer.attempts, result.value, offer.partner_id or "")
        return DispatchOutcome(offer.order_id, result, offer.partner_id,
                               offer.attempts)

    def _claim_partner(self, offer: _Offer) -> str | None:
        candidates = [p for p in self._partners.available()
                      if p.partner_id not in offer.tried]
        while candidates:
            choice = self._strategy.choose(offer.pickup, candidates)
            if choice is None:
                return None
            if self._partners.reserve(choice.partner_id):
                return choice.partner_id
            candidates = [p for p in candidates if p.partner_id != choice.partner_id]
        return None
