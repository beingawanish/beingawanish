"""Version 2, feature 5: idempotent payments with deposit hold, capture, release."""
import threading
import unittest
from datetime import date

from car_rental import FixedClock, VehicleCategory
from car_rental_v2 import (
    Branch,
    Damage,
    DamageKind,
    GatewayTimeoutError,
    IdempotencyConflictError,
    InMemoryPaymentGateway,
    InspectionReport,
    PaymentGateway,
    PaymentService,
    PaymentStateError,
    build_desk,
)

TODAY = date(2026, 10, 15)
END = date(2026, 10, 17)   # two days: 2 x 49.99 = 99.98, deposit 200


class LostResponseGateway(PaymentGateway):
    """Does the work, then 'loses' the reply once for the named operation:
    the nastiest failure, because the money really moved."""

    def __init__(self, inner: InMemoryPaymentGateway, fail_once_on: str):
        self.inner = inner
        self._fail_once_on = fail_once_on

    def _maybe_fail(self, op: str) -> None:
        if op == self._fail_once_on:
            self._fail_once_on = ""
            raise GatewayTimeoutError(f"{op}: no response")

    def hold(self, amount, key):
        result = self.inner.hold(amount, key)
        self._maybe_fail("hold")
        return result

    def capture(self, hold_id, amount, key):
        result = self.inner.capture(hold_id, amount, key)
        self._maybe_fail("capture")
        return result

    def release(self, hold_id, key):
        result = self.inner.release(hold_id, key)
        self._maybe_fail("release")
        return result

    def charge(self, amount, key):
        result = self.inner.charge(amount, key)
        self._maybe_fail("charge")
        return result


def make_desk(gateway):
    clock = FixedClock(TODAY)
    desk = build_desk(clock=clock, gateway=gateway, branches=[Branch("DT", "Downtown")])
    desk.add_vehicle("ECO-01", VehicleCategory.ECONOMY, "Toyota", "Corolla", 2023, "DT")
    return desk, clock


def picked_up(gateway):
    desk, clock = make_desk(gateway)
    trip = desk.book("ECO-01", "Jacob", TODAY, END, "DT")
    record = desk.pick_up(trip.reservation_id)
    clock.advance(2)
    desk.return_vehicle(trip.reservation_id)
    return desk, trip, record


class DepositTests(unittest.TestCase):
    def test_pickup_holds_quote_plus_deposit(self):
        gateway = InMemoryPaymentGateway()
        _, _, record = picked_up(gateway)
        self.assertEqual(record.held, 299.98)
        self.assertEqual(gateway.held(record.hold_id), 299.98)

    def test_clean_return_captures_the_quote_and_releases_the_deposit(self):
        gateway = InMemoryPaymentGateway()
        desk, trip, record = picked_up(gateway)
        s = desk.complete_inspection(trip.reservation_id, InspectionReport()).settlement
        self.assertEqual((s.captured, s.released, s.extra_charged), (99.98, 200.0, 0.0))
        self.assertEqual(gateway.held(record.hold_id), 0.0)

    def test_charges_above_the_hold_become_one_extra_charge(self):
        gateway = InMemoryPaymentGateway()
        desk, trip, _ = picked_up(gateway)
        report = InspectionReport(frozenset({Damage(DamageKind.DENT, "hood")}))
        s = desk.complete_inspection(trip.reservation_id, report).settlement
        self.assertEqual((s.final, s.captured, s.extra_charged), (499.98, 299.98, 200.0))


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.gateway = InMemoryPaymentGateway()
        self.payments = PaymentService(self.gateway)
        self.payments.place_hold("r1", 300.0)

    def test_second_hold_for_same_reservation_is_a_no_op(self):
        self.payments.place_hold("r1", 300.0)
        self.assertEqual(len(self.gateway.executed), 1)

    def test_settling_twice_returns_the_first_settlement(self):
        first = self.payments.settle("r1", 120.0)
        moves = len(self.gateway.executed)
        self.assertIs(self.payments.settle("r1", 120.0), first)
        self.assertEqual(len(self.gateway.executed), moves)

    def test_settling_again_with_a_different_amount_is_refused(self):
        self.payments.settle("r1", 120.0)
        with self.assertRaises(IdempotencyConflictError):
            self.payments.settle("r1", 150.0)

    def test_gateway_refuses_a_reused_key_with_a_new_amount(self):
        self.gateway.charge(10.0, "k1")
        self.assertEqual(self.gateway.charge(10.0, "k1"), self.gateway.charge(10.0, "k1"))
        with self.assertRaises(IdempotencyConflictError):
            self.gateway.charge(11.0, "k1")

    def test_settle_without_a_hold_is_refused(self):
        with self.assertRaises(PaymentStateError):
            self.payments.settle("nope", 10.0)

    def test_concurrent_settles_capture_once(self):
        barrier = threading.Barrier(4)

        def settle():
            barrier.wait()
            self.payments.settle("r1", 120.0)

        threads = [threading.Thread(target=settle) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        captures = [op for op in self.gateway.executed if " capture " in op]
        self.assertEqual(len(captures), 1)


class LostResponseTests(unittest.TestCase):
    def test_retry_after_lost_capture_reply_moves_money_once(self):
        inner = InMemoryPaymentGateway()
        desk, trip, _ = picked_up(LostResponseGateway(inner, fail_once_on="capture"))
        report = InspectionReport(frozenset({Damage(DamageKind.SCRATCH, "hood")}))
        with self.assertRaises(GatewayTimeoutError):
            desk.complete_inspection(trip.reservation_id, report)
        summary = desk.complete_inspection(trip.reservation_id, report)   # retry
        self.assertEqual([x.label for x in summary.extras], ["damage: scratch (hood)"])
        self.assertEqual([op.split(":")[1].split()[0] for op in inner.executed],
                         ["hold", "capture", "release"])


if __name__ == "__main__":
    unittest.main()
