"""Ports of the inventory application layer. Adapters implement them on the unit of work."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from edacommon.envelope import OutgoingMessage

from inventory_svc.domain.model import Reservation, Shortage, StockLevel, StockLine


class InventoryRepository(Protocol):
    def get_reservation(self, reservation_id: str, *, for_update: bool = False) -> Reservation | None: ...

    def save_reservation(self, res: Reservation, now: datetime) -> None: ...

    def try_hold(self, lines: tuple[StockLine, ...]) -> list[Shortage]:
        """All-or-nothing conditional reserve. Empty list = held; otherwise nothing changed."""
        ...

    def release_held(self, lines: tuple[StockLine, ...]) -> None: ...

    def allocate(self, lines: tuple[StockLine, ...]) -> None: ...

    def return_allocated(self, lines: tuple[StockLine, ...]) -> None: ...

    def add_on_hand(self, lines: tuple[StockLine, ...]) -> None: ...

    def set_on_hand(self, sku: str, on_hand: int) -> None: ...

    def levels(self, skus: list[str]) -> list[StockLevel]: ...

    def due_expiries(self, now: datetime, limit: int) -> list[Reservation]: ...

    def restock_seen(self, restock_id: str) -> tuple[StockLine, ...] | None: ...

    def record_restock(
        self, restock_id: str, order_id: str, return_id: str, lines: tuple[StockLine, ...], now: datetime
    ) -> None: ...


class EventPublisher(Protocol):
    def publish(self, msg: OutgoingMessage) -> None: ...
