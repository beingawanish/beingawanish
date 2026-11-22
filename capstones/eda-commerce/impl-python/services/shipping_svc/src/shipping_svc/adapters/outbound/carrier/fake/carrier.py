"""The fake carrier (admin.yaml ``FakeCarrierConfig``): an outbound adapter behind the :class:`Carrier`
port that books shipments and then sends signed tracking webhooks, badly on purpose.

* ``bookingFailureRate``: the booking API fails (:class:`CarrierUnavailable`); shipping-svc retries.
* After a booking the carrier plans PICKED_UP, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, one every
  ``stepDelayMs`` (carrier timestamps ``occurredAt`` follow the plan). ``exceptionRate`` inserts an
  ``EXCEPTION`` (``DELAYED``) after IN_TRANSIT.
* ``outOfOrderRate``: a planned webhook swaps its send time with the next one, so "delivered" can
  arrive before "out for delivery". The carrier timestamp stays honest.
* ``duplicateRate``: a webhook is sent twice with the same ``carrierEventId``.
* ``stepDelayMs <= 0`` disables automatic progress; ``POST .../advance`` (admin.yaml) sends the next
  planned webhook now, or one for ``toStatus``.

Booking is idempotent on ``shipmentId`` and the tracking number is derived from it, so a re-booking
after a rollback (or a restart of the fake) returns the same tracking number. Plans are in memory.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from edacommon.ids import new_id, rfc3339
from edacommon.logging import get_logger
from edacommon.webhooks import sign

from shipping_svc.application.ports import Booking, CarrierUnavailable
from shipping_svc.domain.model import Direction

log = get_logger(__name__)
CARRIER_NAME = "fake-carrier"
PLAN = ("PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED")


@dataclass(frozen=True)
class FakeCarrierConfig:
    duplicateRate: float = 0.2  # noqa: N815 - API names (admin.yaml)
    outOfOrderRate: float = 0.2  # noqa: N815
    exceptionRate: float = 0.02  # noqa: N815
    stepDelayMs: int = 30000  # noqa: N815
    bookingFailureRate: float = 0.02  # noqa: N815

    def merged(self, patch: dict[str, object]) -> FakeCarrierConfig:
        allowed = {k: v for k, v in patch.items() if k in asdict(self)}
        return replace(self, **allowed)  # type: ignore[arg-type]


RATES = ("duplicateRate", "outOfOrderRate", "exceptionRate", "bookingFailureRate")


@dataclass
class _Planned:
    body: dict[str, Any]
    send_at: float  # monotonic seconds; inf = only on advance
    copies: int = 1
    sent: bool = False


@dataclass
class _Tracking:
    shipment_id: str
    tracking_number: str
    planned: list[_Planned] = field(default_factory=list)


class FakeCarrier:
    """Implements :class:`shipping_svc.application.ports.Carrier` and sends the tracking webhooks."""

    name = CARRIER_NAME

    def __init__(
        self,
        config: FakeCarrierConfig,
        *,
        url: str,
        secret: str,
        send: Callable[[str, dict[str, str], bytes], None] | None = None,
        seed: int | None = None,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._url = url
        self._secret = secret
        self._send = send or self._http_send
        self._rng = random.Random(seed)  # noqa: S311 - simulation, not crypto
        self._wall = wall_clock
        self._mono = monotonic
        self._lock = threading.Condition()
        self._by_shipment: dict[str, _Tracking] = {}
        self._by_tracking: dict[str, _Tracking] = {}
        self._stop = False
        self.bookings: dict[str, int] = {}  # shipmentId -> number of successful book() calls

    # -------------------------------------------------------------------------------- port
    def book(self, *, shipment_id: str, direction: Direction, address: dict[str, Any], parcel_count: int) -> Booking:
        with self._lock:
            t = self._by_shipment.get(shipment_id)
            if t is None and self._rng.random() < self.config.bookingFailureRate:
                raise CarrierUnavailable("fake carrier: booking API returned 503")
            self.bookings[shipment_id] = self.bookings.get(shipment_id, 0) + 1
            if t is None:
                t = _Tracking(shipment_id, tracking_number_for(shipment_id))
                self._by_shipment[shipment_id] = t
                self._by_tracking[t.tracking_number] = t
                self._plan(t)
                self._lock.notify()
            return Booking(CARRIER_NAME, t.tracking_number)

    # ------------------------------------------------------------------------------ planning
    def _plan(self, t: _Tracking) -> None:
        c = self.config
        step = c.stepDelayMs / 1000
        start_wall = self._wall()
        start = self._mono()
        statuses: list[tuple[str, str | None]] = []
        for s in PLAN:
            statuses.append((s, None))
            if s == "IN_TRANSIT" and self._rng.random() < c.exceptionRate:
                statuses.append(("EXCEPTION", "DELAYED"))
        for i, (status, code) in enumerate(statuses):
            at = start_wall + timedelta(milliseconds=c.stepDelayMs * (i + 1))
            send_at = start + step * (i + 1) if step > 0 else float("inf")
            copies = 2 if self._rng.random() < c.duplicateRate else 1
            t.planned.append(_Planned(self._body(t, status, at, code), send_at, copies))
        for i in range(len(t.planned) - 1):
            if step > 0 and self._rng.random() < c.outOfOrderRate:
                a, b = t.planned[i], t.planned[i + 1]
                a.send_at, b.send_at = b.send_at, a.send_at

    def _body(self, t: _Tracking, status: str, at: datetime, code: str | None = None) -> dict[str, Any]:
        return {
            "carrierEventId": f"ce_{new_id()}",
            "trackingNumber": t.tracking_number,
            "status": status,
            "exceptionCode": code,
            "location": "Berlin hub" if status in ("PICKED_UP", "IN_TRANSIT") else None,
            "occurredAt": rfc3339(at),
        }

    # ------------------------------------------------------------------------------ admin
    def advance(self, tracking_number: str, to_status: str | None = None, exception_code: str | None = None) -> bool:
        """Send the next planned webhook now (or one for ``to_status``). False: unknown tracking number."""
        with self._lock:
            t = self._by_tracking.get(tracking_number)
            if t is None:
                return False
            now = self._mono()
            target = next(
                (
                    p
                    for p in sorted(t.planned, key=lambda p: PLAN_ORDER.get(p.body["status"], 9))
                    if not p.sent and (to_status is None or p.body["status"] == to_status)
                ),
                None,
            )
            if target is None:
                status = to_status or "DELIVERED"
                code = (exception_code or "DELAYED") if status == "EXCEPTION" else None
                target = _Planned(self._body(t, status, self._wall(), code), now)
                t.planned.append(target)
            target.send_at = now
            self._lock.notify()
            return True

    # ------------------------------------------------------------------------------ delivery
    def due(self, *, force: bool = False) -> list[bytes]:
        """Webhooks due now (all planned ones with ``force``), in send order; marks them sent."""
        now = self._mono()
        with self._lock:
            ready = [p for t in self._by_shipment.values() for p in t.planned if not p.sent and (force or p.send_at <= now)]
            ready.sort(key=lambda p: p.send_at if p.send_at != float("inf") else PLAN_ORDER.get(p.body["status"], 9) + 1e12)
            out: list[bytes] = []
            for p in ready:
                p.sent = True
                raw = json.dumps(p.body, separators=(",", ":")).encode()
                out.extend([raw] * p.copies)
            return out

    def deliver(self, raw: bytes) -> None:
        ts = str(int(self._wall().timestamp()))
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Timestamp": ts,
            "X-Carrier-Signature": sign(self._secret, ts, raw),
        }
        self._send(self._url, headers, raw)

    def flush(self) -> int:
        """Deliver every planned webhook now, in send order (tests)."""
        items = self.due(force=True)
        for raw in items:
            self.deliver(raw)
        return len(items)

    def _http_send(self, url: str, headers: dict[str, str], raw: bytes) -> None:
        import httpx

        for attempt in range(5):  # a real carrier retries until it sees a 2xx
            try:
                r = httpx.post(url, content=raw, headers=headers, timeout=10)
                if r.status_code < 300 or r.status_code in (400, 401):
                    return
            except httpx.HTTPError as exc:
                log.warning("fake carrier webhook delivery failed", attempt=attempt, error=exc)
            time.sleep(2**attempt)

    def run(self) -> None:
        while True:
            with self._lock:
                if self._stop:
                    return
                self._lock.wait(0.5)
            for raw in self.due():
                self.deliver(raw)

    def stop(self) -> None:
        with self._lock:
            self._stop = True
            self._lock.notify()


PLAN_ORDER = {s: i for i, s in enumerate(("PICKED_UP", "IN_TRANSIT", "EXCEPTION", "OUT_FOR_DELIVERY", "DELIVERED"))}


def tracking_number_for(shipment_id: str) -> str:
    """Deterministic per shipment, like a carrier that dedupes on our reference."""
    digits = int(hashlib.sha256(shipment_id.encode()).hexdigest(), 16) % 10**12
    return f"FC{digits:012d}"
