"""Read side for the Orders API (orders.yaml): read model first, write-model fallback for an order
the projector has not seen yet (read-your-writes for the one case that matters, ADR-0010)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from order_svc.domain.saga import TERMINAL, State, customer_status


class ReadModel(Protocol):
    def order(self, order_id: str) -> dict[str, Any] | None: ...

    def orders_of(
        self, customer_id: str, *, limit: int, after: tuple[str, str] | None, statuses: list[str] | None
    ) -> list[dict[str, Any]]: ...


class WriteModel(Protocol):
    def order_with_saga(self, order_id: str) -> tuple[dict[str, Any], str, int] | None:
        """(order view without timeline, saga state, saga version)"""
        ...


@dataclass
class OrderQueries:
    read: ReadModel
    write: WriteModel

    def get(self, order_id: str) -> tuple[dict[str, Any], bool] | None:
        """Return (Order body, still_in_flight)."""
        view = self.read.order(order_id)
        if view is not None:
            view["source"] = "READ_MODEL"
            return view, view["status"] in ("PENDING", "CONFIRMED", "SHIPPED", "RETURN_IN_PROGRESS")
        fallback = self.write.order_with_saga(order_id)
        if fallback is None:
            return None
        body, state, version = fallback
        body["status"] = customer_status(State(state))
        body["version"] = version
        body["timeline"] = []
        body["source"] = "WRITE_MODEL_FALLBACK"
        return body, State(state) not in TERMINAL
