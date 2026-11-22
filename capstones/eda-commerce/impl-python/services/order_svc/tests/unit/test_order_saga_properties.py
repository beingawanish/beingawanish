"""Property test (checklist §11, ADR-0014 layer 1): random interleavings of replies - reordered,
duplicated, lost, late - always end in a terminal or NEEDS_ATTENTION state, with compensations
consistent with what the participants actually did.

The participants are small models of inventory-svc, payment-svc, fulfilment-svc and shipping-svc
that keep state per business id (so resends re-answer, as the real services do).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from order_svc.domain import saga as S

from .sagahelp import Run

W = S.State
ENDS = {W.DELIVERED, W.CANCELLED, W.NEEDS_ATTENTION}


@dataclass
class World:
    draw: Any
    inbox: list[S.Trigger] = field(default_factory=list)
    reservations: dict[str, str] = field(default_factory=dict)   # HELD/COMMITTED/RELEASED/EXPIRED/REJECTED
    payments: dict[str, str] = field(default_factory=dict)       # AUTHORIZED/DECLINED/LOST/VOIDED/CAPTURED/CAPTURE_FAILED
    fulfilments: dict[str, str] = field(default_factory=dict)    # ACCEPTED/PACKED/DISPATCHED/FAILED/CANCELLED/DROPPED
    shipped: bool = False
    seen: int = 0

    def choose(self, options: list[str], label: str) -> str:
        return self.draw(st.sampled_from(options), label=label)  # type: ignore[no-any-return]

    def handle(self, cmd: S.Command) -> None:
        bid = cmd.business_id
        if cmd.name == "ReserveStock":
            st_ = self.reservations.get(bid)
            if st_ is None:
                st_ = self.choose(["HELD", "HELD", "REJECTED", "LOST"], "reserve")
                if st_ == "LOST":
                    return  # command lost: the saga deadline must recover
                self.reservations[bid] = st_
            if st_ in ("HELD", "COMMITTED"):
                self.inbox.append(S.StockReserved(bid))
            elif st_ == "REJECTED":
                self.inbox.append(S.StockReservationRejected(bid))
            elif st_ == "EXPIRED":
                self.inbox.append(S.ReservationExpired(bid))
            else:
                self.inbox.append(S.ReservationReleased(bid))
        elif cmd.name == "CommitReservation":
            st_ = self.reservations.get(bid)
            if st_ == "HELD":
                self.reservations[bid] = "COMMITTED"
                self.inbox.append(S.ReservationCommitted(bid))
            elif st_ == "COMMITTED":
                self.inbox.append(S.ReservationCommitted(bid))
            else:
                self.reservations[bid] = "EXPIRED" if st_ in (None, "HELD", "EXPIRED") else st_
                self.inbox.append(S.ReservationExpired(bid))
        elif cmd.name == "ReleaseReservation":
            st_ = self.reservations.get(bid)
            if st_ in (None, "HELD", "COMMITTED", "RELEASED"):
                self.reservations[bid] = "RELEASED"
            self.inbox.append(S.ReservationReleased(bid))
        elif cmd.name == "AuthorizePayment":
            st_ = self.payments.get(bid)
            if st_ is None:
                st_ = self.choose(["AUTHORIZED", "AUTHORIZED", "DECLINED", "LOST"], "authorize")
                self.payments[bid] = st_
            if st_ in ("AUTHORIZED", "CAPTURED", "CAPTURE_FAILED"):
                self.inbox.append(S.PaymentAuthorized(bid))
            elif st_ == "DECLINED":
                self.inbox.append(S.PaymentDeclined(bid, "CARD_DECLINED"))
            elif st_ == "LOST" and self.choose(["silent", "late"], "lost-auth") == "late":
                self.payments[bid] = "AUTHORIZED"
                self.inbox.append(S.PaymentAuthorized(bid))
        elif cmd.name == "VoidPayment":
            st_ = self.payments.get(bid)
            if st_ in ("CAPTURED",):
                raise AssertionError("saga voided a captured payment")
            self.payments[bid] = "VOIDED"
            self.inbox.append(S.PaymentVoided(bid))
        elif cmd.name == "CapturePayment":
            st_ = self.payments.get(bid)
            assert st_ in ("AUTHORIZED", "CAPTURED", "CAPTURE_FAILED"), f"capture of {st_}"
            if st_ == "CAPTURE_FAILED":
                self.inbox.append(S.PaymentCaptureFailed(bid, "AUTHORIZATION_EXPIRED", False))
                return
            outcome = "CAPTURED" if st_ == "CAPTURED" else self.choose(["CAPTURED", "CAPTURED", "RETRY", "FAIL"], "capture")
            if outcome == "CAPTURED":
                self.payments[bid] = "CAPTURED"
                self.inbox.append(S.PaymentCaptured(bid))
            elif outcome == "RETRY":
                self.inbox.append(S.PaymentCaptureFailed(bid, "PSP_ERROR", True))
            else:
                self.payments[bid] = "CAPTURE_FAILED"
                self.inbox.append(S.PaymentCaptureFailed(bid, "AUTHORIZATION_EXPIRED", False))
        elif cmd.name == "RequestFulfilment":
            st_ = self.fulfilments.get(bid)
            if st_ in (None, "DROPPED"):
                st_ = self.choose(["ACCEPTED", "ACCEPTED", "DROPPED", "FAILED"], "wms")
                self.fulfilments[bid] = st_
            if st_ == "FAILED":
                self.inbox.append(S.FulfilmentFailed(bid, "STOCK_DAMAGED"))
            elif st_ != "DROPPED":
                self.inbox.append(S.FulfilmentAccepted(bid))
                if st_ == "ACCEPTED":
                    self.fulfilments[bid] = "DISPATCHED"
                    self.inbox.extend([S.OrderPacked(bid), S.ShipmentCreated("ship-1", "fake", "FC1"),
                                       S.OrderDispatched(bid, "ship-1")])
                    if self.choose(["deliver", "lost"], "carrier") == "deliver":
                        self.inbox.append(S.ShipmentDelivered("ship-1", "2026-11-20T10:00:00+00:00"))
                    else:
                        self.inbox.append(S.ShipmentException("ship-1", "LOST"))
        elif cmd.name == "CancelFulfilment":
            self.fulfilments[bid] = "CANCELLED"
            self.inbox.append(S.FulfilmentCancelled(bid))


def run_world(data: Any) -> tuple[Run, World]:
    r = Run.started()
    w = World(data.draw)
    for c in r.commands:
        w.handle(c)
    w.seen = len(r.commands)
    for _ in range(60):
        if r.state in (W.DELIVERED, W.CANCELLED):
            break
        action = data.draw(st.sampled_from(["deliver", "deliver", "deliver", "duplicate", "deadline", "expire"]),
                           label="action")
        if action in ("deliver", "duplicate") and w.inbox:
            i = data.draw(st.integers(0, len(w.inbox) - 1), label="which")
            t = w.inbox[i] if action == "duplicate" else w.inbox.pop(i)
            r.send(t)
        elif action == "deadline" and r.deadline is not None:
            r.deadline_fires()
        elif action == "expire":
            held = [k for k, v in w.reservations.items() if v == "HELD"]
            if held:
                w.reservations[held[0]] = "EXPIRED"
                w.inbox.append(S.ReservationExpired(held[0]))
        for c in r.commands[w.seen:]:
            w.handle(c)
        w.seen = len(r.commands)
    # Settle: deliver everything in order and let deadlines fire, as the real system would.
    for _ in range(200):
        if r.state in ENDS and not w.inbox:
            break
        if w.inbox:
            r.send(w.inbox.pop(0))
        elif r.deadline is not None:
            r.deadline_fires()
        else:
            break
        for c in r.commands[w.seen:]:
            w.handle(c)
        w.seen = len(r.commands)
    return r, w


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.data())
def test_random_interleavings_end_consistently(data: Any) -> None:
    r, w = run_world(data)
    assert r.state in ENDS, f"stuck in {r.state} with deadline {r.deadline}"
    names = r.cmd_names()
    rid = r.data.reservation_id
    pid = r.data.payment_id
    if r.state is W.CANCELLED:
        assert "CapturePayment" not in names, "never cancel past the pivot"
        assert w.reservations.get(rid) in (None, "RELEASED", "EXPIRED", "REJECTED"), w.reservations
        if pid:
            assert w.payments.get(pid) in (None, "VOIDED", "DECLINED", "LOST"), w.payments
        assert r.events[-1].name == "OrderCancelled" or "OrderCancelled" in r.evt_names()
    if r.state is W.DELIVERED:
        assert pid and w.payments[pid] == "CAPTURED"
        assert "VoidPayment" not in names and "ReleaseReservation" not in names
        assert r.evt_names().count("InvoiceIssued") == 1 and r.evt_names().count("OrderDelivered") == 1
    if "CapturePayment" in names:
        assert "VoidPayment" not in names or r.state is not W.DELIVERED
    # Events tell one story: never both confirmed-and-cancelled-and-delivered, at most one of each.
    for e in ("OrderPlaced", "OrderConfirmed", "OrderCancelled", "OrderDelivered", "InvoiceIssued"):
        assert r.evt_names().count(e) <= 1, (e, r.evt_names())
    assert not ("OrderCancelled" in r.evt_names() and "OrderDelivered" in r.evt_names())
    # Business ids were minted once.
    assert len({c.business_id for c in r.commands if c.name in ("ReserveStock", "CommitReservation", "ReleaseReservation")}) == 1


@settings(max_examples=100, deadline=None)
@given(st.permutations(["reserved", "expired", "authorized"]))
def test_expiry_race_orders(order: list[str]) -> None:
    """Whatever order StockReserved / ReservationExpired / PaymentAuthorized arrive in, the saga
    never confirms an order whose reservation expired."""
    r = Run.started()
    r.stock_reserved()
    pid = r.data.payment_id or ""
    for step in order:
        if step == "reserved":
            r.send(S.StockReserved(r.data.reservation_id))
        elif step == "expired":
            r.send(S.ReservationExpired(r.data.reservation_id))
        else:
            r.send(S.PaymentAuthorized(pid))
    assert "OrderConfirmed" not in r.evt_names()
    if r.state is W.CANCELLING:
        r.send(S.PaymentVoided(pid), after=timedelta(seconds=1))
    assert r.state is W.CANCELLED and r.data.cancel_reason == "RESERVATION_EXPIRED"
