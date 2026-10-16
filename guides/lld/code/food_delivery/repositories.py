"""Repositories: restaurants, partners and orders, behind ABCs.

Each in-memory implementation has its own lock around its own dict.
PartnerRepository.reserve() is the atomic "claim this partner if free" step,
the same compare-and-set a database would do with a conditional UPDATE.
"""
import itertools
import threading
from abc import ABC, abstractmethod

from .models import DeliveryPartner, Order, Restaurant


class RestaurantRepository(ABC):
    @abstractmethod
    def add(self, restaurant: Restaurant) -> None: ...
    @abstractmethod
    def get(self, restaurant_id: str) -> Restaurant | None: ...


class InMemoryRestaurants(RestaurantRepository):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._restaurants: dict[str, Restaurant] = {}

    def add(self, restaurant: Restaurant) -> None:
        with self._lock:
            self._restaurants[restaurant.restaurant_id] = restaurant

    def get(self, restaurant_id: str) -> Restaurant | None:
        with self._lock:
            return self._restaurants.get(restaurant_id)


class PartnerRepository(ABC):
    @abstractmethod
    def add(self, partner: DeliveryPartner) -> None: ...
    @abstractmethod
    def get(self, partner_id: str) -> DeliveryPartner | None: ...
    @abstractmethod
    def available(self) -> list[DeliveryPartner]: ...
    @abstractmethod
    def reserve(self, partner_id: str) -> bool:
        """Mark the partner busy if they are free. True if this call won."""
    @abstractmethod
    def release(self, partner_id: str) -> None: ...


class InMemoryPartners(PartnerRepository):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._partners: dict[str, DeliveryPartner] = {}

    def add(self, partner: DeliveryPartner) -> None:
        with self._lock:
            self._partners[partner.partner_id] = partner

    def get(self, partner_id: str) -> DeliveryPartner | None:
        with self._lock:
            return self._partners.get(partner_id)

    def available(self) -> list[DeliveryPartner]:
        with self._lock:
            return [p for p in self._partners.values() if p.available]

    def reserve(self, partner_id: str) -> bool:
        with self._lock:
            partner = self._partners.get(partner_id)
            if partner is None or not partner.available:
                return False
            partner.available = False
            return True

    def release(self, partner_id: str) -> None:
        with self._lock:
            partner = self._partners.get(partner_id)
            if partner is not None:
                partner.available = True


class OrderRepository(ABC):
    @abstractmethod
    def next_id(self) -> str: ...
    @abstractmethod
    def add(self, order: Order) -> None: ...
    @abstractmethod
    def get(self, order_id: str) -> Order | None: ...
    @abstractmethod
    def save(self, order: Order) -> None: ...
    @abstractmethod
    def find_by_key(self, customer_id: str, idempotency_key: str) -> Order | None: ...
    @abstractmethod
    def all(self) -> list[Order]: ...


class InMemoryOrders(OrderRepository):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._orders: dict[str, Order] = {}
        self._by_key: dict[tuple[str, str], str] = {}

    def next_id(self) -> str:
        with self._lock:
            return f"ORD-{next(self._ids):04d}"

    def add(self, order: Order) -> None:
        with self._lock:
            self._orders[order.order_id] = order
            self._by_key[(order.customer_id, order.idempotency_key)] = order.order_id

    def get(self, order_id: str) -> Order | None:
        with self._lock:
            return self._orders.get(order_id)

    def save(self, order: Order) -> None:
        with self._lock:
            self._orders[order.order_id] = order

    def find_by_key(self, customer_id: str, idempotency_key: str) -> Order | None:
        with self._lock:
            order_id = self._by_key.get((customer_id, idempotency_key))
            return self._orders.get(order_id) if order_id else None

    def all(self) -> list[Order]:
        with self._lock:
            return list(self._orders.values())
