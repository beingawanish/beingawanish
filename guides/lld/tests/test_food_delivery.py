"""Tests for food delivery. Time is frozen via FixedClock throughout."""
import sys
import threading
import unittest
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

# The package lives in code/ next to tests/. This makes it importable when
# the suite runs from the folder that holds both.
CODE_DIR = Path(__file__).resolve().parent.parent / "code"
if CODE_DIR.is_dir() and str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from food_delivery import (
    TERMINAL,
    Actor,
    CancellationNotAllowedError,
    CouponNotApplicableError,
    DeliveryPartner,
    DispatchConfig,
    DispatchResult,
    DistanceEtaEstimator,
    EmptyCartError,
    EtaConfig,
    EventKind,
    FixedClock,
    FlatOffCoupon,
    FoodDeliveryConfig,
    FoodDeliveryService,
    FreeDeliveryAbove,
    IdempotencyKeyReusedError,
    InMemoryPartners,
    InMemoryRestaurants,
    InvalidCouponError,
    InvalidQuantityError,
    InvalidTransitionError,
    ItemUnavailableError,
    Location,
    MenuItem,
    MixedRestaurantCartError,
    NoActiveOfferError,
    Notifier,
    OrderObserver,
    OrderStatus,
    PartnerMismatchError,
    PercentOffCoupon,
    PricingConfig,
    RecordingObserver,
    Restaurant,
    RestaurantClosedError,
    chain,
)

NOW = datetime(2026, 10, 16, 19, 30, tzinfo=UTC)
HOME = Location(3, 4)               # 5 km from R1 at the origin


def make_service(now=NOW, observers=(), config=None):
    clock = FixedClock(now)
    restaurants, partners = InMemoryRestaurants(), InMemoryPartners()
    restaurants.add(Restaurant(
        "R1", "Biryani House", Location(0, 0), time(10, 0), time(23, 0), 20,
        menu={"biryani": MenuItem("biryani", "Chicken Biryani", Decimal(249)),
              "paneer": MenuItem("paneer", "Paneer Tikka", Decimal(199)),
              "jamun": MenuItem("jamun", "Gulab Jamun", Decimal(79))}))
    restaurants.add(Restaurant(
        "R2", "Dosa Corner", Location(2, 1), time(7, 0), time(22, 0), 10,
        menu={"dosa": MenuItem("dosa", "Masala Dosa", Decimal(120))}))
    partners.add(DeliveryPartner("P1", "Ravi", Location(1, 0)))
    partners.add(DeliveryPartner("P2", "Meena", Location(0, 2)))
    partners.add(DeliveryPartner("P3", "Arjun", Location(9, 9)))
    svc = FoodDeliveryService(
        clock=clock, config=config or FoodDeliveryConfig(),
        restaurants=restaurants, partners=partners,
        discounts=chain(
            PercentOffCoupon("FEAST20", Decimal(20), cap=Decimal(100),
                             min_item_total=Decimal(300)),
            FlatOffCoupon("FLAT50", Decimal(50), min_item_total=Decimal(200)),
            FreeDeliveryAbove(Decimal(499))),
        notifier=Notifier(observers))
    return svc, clock, partners


def placed_order(svc, key="k1", coupon=None):
    svc.add_to_cart("awanish", "R1", "biryani", 2)
    svc.add_to_cart("awanish", "R1", "jamun")
    return svc.place_order("awanish", HOME, key, coupon)


class CartTests(unittest.TestCase):
    def setUp(self):
        self.svc, _, _ = make_service()

    def test_second_restaurant_is_rejected(self):
        self.svc.add_to_cart("awanish", "R1", "biryani")
        with self.assertRaises(MixedRestaurantCartError):
            self.svc.add_to_cart("awanish", "R2", "dosa")
        self.assertEqual(self.svc.cart("awanish"), {"biryani": 1})

    def test_replace_switches_restaurant(self):
        self.svc.add_to_cart("awanish", "R1", "biryani")
        self.svc.add_to_cart("awanish", "R2", "dosa", replace=True)
        self.assertEqual(self.svc.cart("awanish"), {"dosa": 1})

    def test_quantity_must_be_positive(self):
        with self.assertRaises(InvalidQuantityError):
            self.svc.add_to_cart("awanish", "R1", "biryani", 0)

    def test_quantity_cap_per_line(self):
        self.svc.add_to_cart("awanish", "R1", "biryani", 20)
        with self.assertRaises(InvalidQuantityError):
            self.svc.add_to_cart("awanish", "R1", "biryani", 1)

    def test_remove_last_item_frees_restaurant_rule(self):
        self.svc.add_to_cart("awanish", "R1", "biryani", 2)
        self.svc.remove_from_cart("awanish", "biryani", 1)
        self.assertEqual(self.svc.cart("awanish"), {"biryani": 1})
        self.svc.remove_from_cart("awanish", "biryani")
        self.svc.add_to_cart("awanish", "R2", "dosa")
        self.assertEqual(self.svc.cart("awanish"), {"dosa": 1})

    def test_unavailable_item_cannot_be_added(self):
        self.svc.set_item_available("R1", "paneer", False)
        with self.assertRaises(ItemUnavailableError):
            self.svc.add_to_cart("awanish", "R1", "paneer")


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.svc, _, _ = make_service()
        self.svc.add_to_cart("awanish", "R1", "biryani", 2)
        self.svc.add_to_cart("awanish", "R1", "jamun")      # food 577.00

    def test_plain_bill_gets_free_delivery_over_threshold(self):
        bill = self.svc.quote("awanish", HOME)
        # 577 >= 499, so delivery 25 + 8 x 5 = 65 is waived; tax 5% of 577
        self.assertEqual((bill.item_total, bill.delivery_fee, bill.tax, bill.total),
                         (Decimal("577.00"), Decimal("0.00"),
                          Decimal("28.85"), Decimal("605.85")))

    def test_percent_coupon_is_capped_and_runs_before_free_delivery(self):
        bill = self.svc.quote("awanish", HOME, "feast20")
        # 20% of 577 = 115.40, capped at 100; 477 < 499 so delivery is charged
        self.assertEqual((bill.discount, bill.delivery_fee, bill.tax, bill.total),
                         (Decimal("100.00"), Decimal("65.00"),
                          Decimal("23.85"), Decimal("565.85")))

    def test_flat_coupon(self):
        bill = self.svc.quote("awanish", HOME, "FLAT50")
        self.assertEqual(bill.discount, Decimal("50.00"))
        self.assertEqual(bill.delivery_fee, Decimal("0.00"))   # 527 >= 499

    def test_minimum_spend_not_met(self):
        self.svc.remove_from_cart("awanish", "biryani")         # food 79.00
        with self.assertRaises(CouponNotApplicableError):
            self.svc.quote("awanish", HOME, "FEAST20")

    def test_unknown_coupon(self):
        with self.assertRaises(InvalidCouponError):
            self.svc.quote("awanish", HOME, "NOPE")

    def test_tax_rate_comes_from_config(self):
        svc, _, _ = make_service(config=FoodDeliveryConfig(
            pricing=PricingConfig(tax_rate=Decimal("0.18"))))
        svc.add_to_cart("awanish", "R1", "jamun")
        self.assertEqual(svc.quote("awanish", HOME).tax, Decimal("14.22"))


class CheckoutTests(unittest.TestCase):
    def test_empty_cart(self):
        svc, _, _ = make_service()
        with self.assertRaises(EmptyCartError):
            svc.place_order("awanish", HOME, "k1")

    def test_closed_restaurant(self):
        svc, _, _ = make_service(now=datetime(2026, 10, 16, 23, 0, tzinfo=UTC))
        svc.add_to_cart("awanish", "R1", "biryani")
        with self.assertRaises(RestaurantClosedError):
            svc.place_order("awanish", HOME, "k1")

    def test_paused_restaurant(self):
        svc, _, _ = make_service()
        svc.add_to_cart("awanish", "R1", "biryani")
        svc.set_paused("R1", True)
        with self.assertRaises(RestaurantClosedError):
            svc.place_order("awanish", HOME, "k1")

    def test_item_sold_out_after_adding(self):
        svc, _, _ = make_service()
        svc.add_to_cart("awanish", "R1", "biryani")
        svc.set_item_available("R1", "biryani", False)
        with self.assertRaises(ItemUnavailableError):
            svc.place_order("awanish", HOME, "k1")

    def test_eta_at_placement(self):
        svc, _, _ = make_service()
        order = placed_order(svc)
        # prep 20 + ride 5 km at 20 km/h = 15 + buffer 5
        self.assertEqual(order.eta, NOW + timedelta(minutes=40))


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.svc, _, _ = make_service()

    def test_same_key_returns_same_order(self):
        first = placed_order(self.svc, key="k1")
        again = self.svc.place_order("awanish", HOME, "k1")
        self.assertIs(again, first)
        self.assertEqual(self.svc.cart("awanish"), {})

    def test_same_key_different_request_is_rejected(self):
        placed_order(self.svc, key="k1")
        with self.assertRaises(IdempotencyKeyReusedError):
            self.svc.place_order("awanish", HOME, "k1", "FEAST20")

    def test_new_key_is_a_new_order(self):
        first = placed_order(self.svc, key="k1")
        second = placed_order(self.svc, key="k2")
        self.assertNotEqual(first.order_id, second.order_id)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.svc, _, _ = make_service()
        self.order = placed_order(self.svc)
        self.oid = self.order.order_id

    def run_to_ready(self):
        self.svc.accept(self.oid)
        self.svc.partner_accept(self.oid, "P1")
        self.svc.start_preparing(self.oid)
        self.svc.mark_ready(self.oid)

    def test_happy_path_history(self):
        self.run_to_ready()
        self.svc.pick_up(self.oid, "P1")
        self.svc.deliver(self.oid, "P1")
        self.assertEqual([c.status for c in self.order.history], [
            OrderStatus.PLACED, OrderStatus.ACCEPTED, OrderStatus.PREPARING,
            OrderStatus.READY, OrderStatus.PICKED_UP, OrderStatus.DELIVERED])

    def test_cannot_skip_a_state(self):
        with self.assertRaises(InvalidTransitionError):
            self.svc.mark_ready(self.oid)

    def test_terminal_states_have_no_exits(self):
        self.assertEqual(TERMINAL, {OrderStatus.DELIVERED, OrderStatus.REJECTED,
                                    OrderStatus.CANCELLED})

    def test_wrong_partner_cannot_pick_up(self):
        self.run_to_ready()
        with self.assertRaises(PartnerMismatchError):
            self.svc.pick_up(self.oid, "P2")

    def test_partner_freed_after_delivery(self):
        self.run_to_ready()
        self.svc.pick_up(self.oid, "P1")
        self.svc.deliver(self.oid, "P1")
        second = placed_order(self.svc, key="k2")
        self.svc.accept(second.order_id)
        self.svc.partner_accept(second.order_id, "P1")   # nearest again
        self.assertEqual(second.partner_id, "P1")


class RefundTests(unittest.TestCase):
    def setUp(self):
        self.svc, _, _ = make_service()
        self.order = placed_order(self.svc)              # total 605.85
        self.oid = self.order.order_id

    def test_customer_cancel_before_accept_is_full_refund(self):
        self.svc.cancel(self.oid)
        self.assertEqual(self.order.refund, Decimal("605.85"))

    def test_customer_cancel_while_preparing_is_half(self):
        self.svc.accept(self.oid)
        self.svc.start_preparing(self.oid)
        self.svc.cancel(self.oid)
        self.assertEqual(self.order.refund, Decimal("302.93"))

    def test_customer_cannot_cancel_when_ready(self):
        self.svc.accept(self.oid)
        self.svc.start_preparing(self.oid)
        self.svc.mark_ready(self.oid)
        with self.assertRaises(CancellationNotAllowedError):
            self.svc.cancel(self.oid)

    def test_restaurant_rejection_is_full_refund(self):
        self.svc.reject(self.oid)
        self.assertEqual(self.order.status, OrderStatus.REJECTED)
        self.assertEqual(self.order.refund, Decimal("605.85"))

    def test_restaurant_can_cancel_ready_order_with_full_refund(self):
        self.svc.accept(self.oid)
        self.svc.start_preparing(self.oid)
        self.svc.mark_ready(self.oid)
        self.svc.cancel(self.oid, Actor.RESTAURANT)
        self.assertEqual(self.order.refund, Decimal("605.85"))


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.clock, self.partners = make_service()
        self.order = placed_order(self.svc)
        self.oid = self.order.order_id

    def test_nearest_partner_gets_first_offer(self):
        self.svc.accept(self.oid)
        self.assertFalse(self.partners.get("P1").available)
        self.assertTrue(self.partners.get("P2").available)

    def test_timeout_moves_offer_and_frees_first_partner(self):
        self.svc.accept(self.oid)
        self.clock.advance(seconds=29)
        self.assertEqual(self.svc.tick(), [])
        self.clock.advance(seconds=1)
        [outcome] = self.svc.tick()
        self.assertEqual((outcome.result, outcome.partner_id, outcome.attempt),
                         (DispatchResult.OFFERED, "P2", 2))
        self.assertTrue(self.partners.get("P1").available)
        with self.assertRaises(PartnerMismatchError):
            self.svc.partner_accept(self.oid, "P1")

    def test_decline_reassigns_immediately(self):
        self.svc.accept(self.oid)
        self.svc.partner_decline(self.oid, "P1")
        self.svc.partner_accept(self.oid, "P2")
        self.assertEqual(self.order.partner_id, "P2")

    def test_no_partner_in_range_waits(self):
        self.partners.reserve("P1")
        self.partners.reserve("P2")                     # only P3, 12.7 km away
        self.svc.accept(self.oid)
        self.clock.advance(seconds=30)
        [outcome] = self.svc.tick()
        self.assertEqual(outcome.result, DispatchResult.WAITING)

    def test_exhausted_attempts_cancel_with_full_refund(self):
        self.svc.accept(self.oid)                       # attempt 1: P1
        with self.assertLogs("food_delivery.dispatch", level="WARNING"):
            for _ in range(3):                          # attempts 2, 3, then fail
                self.clock.advance(seconds=30)
                self.svc.tick()
        self.assertEqual(self.order.status, OrderStatus.CANCELLED)
        self.assertEqual(self.order.history[-1].actor, Actor.PLATFORM)
        self.assertEqual(self.order.refund, self.order.bill.total)
        self.assertTrue(all(self.partners.get(p).available for p in ("P1", "P2")))

    def test_accept_after_assignment_is_rejected(self):
        self.svc.accept(self.oid)
        self.svc.partner_accept(self.oid, "P1")
        with self.assertRaises(NoActiveOfferError):
            self.svc.partner_accept(self.oid, "P1")

    def test_accepted_offer_never_times_out(self):
        self.svc.accept(self.oid)
        self.svc.partner_accept(self.oid, "P1")
        self.clock.advance(minutes=10)
        self.assertEqual(self.svc.tick(), [])

    def test_eta_recomputed_on_assignment(self):
        self.svc.accept(self.oid)
        self.clock.advance(minutes=2)
        self.svc.partner_accept(self.oid, "P1")
        # Ravi is 1 km away (3 min) but the kitchen needs 20: 20 + 15 + 5
        self.assertEqual(self.svc.eta(self.oid),
                         NOW + timedelta(minutes=2 + 40))


class EtaTests(unittest.TestCase):
    def test_slow_partner_dominates_prep(self):
        estimator = DistanceEtaEstimator(EtaConfig(rider_speed_kmph=20, buffer_minutes=5))
        restaurant = Restaurant("R9", "Quick Bites", Location(0, 0),
                                time(0, 0), time(23, 59), 5)
        # partner 4 km out = 12 min > 5 min prep; ride 2 km = 6; buffer 5
        self.assertEqual(estimator.estimate(restaurant, Location(2, 0), Location(0, 4)),
                         timedelta(minutes=23))


class NotificationTests(unittest.TestCase):
    def test_observer_sees_status_changes_in_order(self):
        recorder = RecordingObserver()
        svc, _, _ = make_service(observers=[recorder])
        order = placed_order(svc)
        svc.accept(order.order_id)
        kinds = [(e.kind, e.status) for e in recorder.events]
        self.assertEqual(kinds, [
            (EventKind.STATUS_CHANGED, OrderStatus.PLACED),
            (EventKind.STATUS_CHANGED, OrderStatus.ACCEPTED),
            (EventKind.PARTNER_OFFERED, OrderStatus.ACCEPTED)])

    def test_failing_observer_does_not_break_the_order(self):
        class Broken(OrderObserver):
            def on_event(self, event):
                raise RuntimeError("SMS gateway down")

        recorder = RecordingObserver()
        svc, _, _ = make_service(observers=[Broken(), recorder])
        with self.assertLogs("food_delivery.notifications", level="ERROR"):
            order = placed_order(svc)
        self.assertEqual(order.status, OrderStatus.PLACED)
        self.assertEqual(len(recorder.events), 1)


class ConfigTests(unittest.TestCase):
    def test_bad_values_fail_at_startup(self):
        with self.assertRaises(ValueError):
            PricingConfig(tax_rate=Decimal("1.5"))
        with self.assertRaises(ValueError):
            DispatchConfig(max_offer_attempts=0)

    def test_blank_menu_item_rejected(self):
        with self.assertRaises(ValueError):
            MenuItem("x", "  ", Decimal(10))


class ConcurrencyTests(unittest.TestCase):
    def run_threads(self, target, count):
        barrier = threading.Barrier(count)

        def wrapped(i):
            barrier.wait()
            target(i)

        threads = [threading.Thread(target=wrapped, args=(i,)) for i in range(count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def test_same_key_from_many_threads_makes_one_order(self):
        svc, _, _ = make_service()
        svc.add_to_cart("awanish", "R1", "biryani")
        ids = []
        self.run_threads(
            lambda i: ids.append(svc.place_order("awanish", HOME, "k1").order_id), 8)
        self.assertEqual(set(ids), {"ORD-0001"})
        self.assertEqual(len(ids), 8)

    def test_one_partner_two_orders_one_offer(self):
        svc, _, partners = make_service()
        partners.reserve("P2")                          # leave only P1 in range
        orders = []
        for customer in ("awanish", "shyam"):
            svc.add_to_cart(customer, "R1", "biryani")
            orders.append(svc.place_order(customer, HOME, "k1"))
        self.run_threads(lambda i: svc.accept(orders[i].order_id), 2)
        results = []
        for o in orders:
            try:
                svc.partner_accept(o.order_id, "P1")
                results.append("ok")
            except PartnerMismatchError:
                results.append("mismatch")
        self.assertEqual(sorted(results), ["mismatch", "ok"])


if __name__ == "__main__":
    unittest.main()
