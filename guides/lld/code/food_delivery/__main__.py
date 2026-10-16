"""Runnable slice: cart, bill, idempotent checkout, dispatch with a timeout,
delivery, and a customer cancellation with a partial refund.

Uses a FixedClock, so the output is identical on every run.
Run from the project folder:  python3 -m food_delivery
"""
import logging
from datetime import UTC, datetime, time
from decimal import Decimal

from food_delivery import (
    DeliveryPartner,
    FixedClock,
    FoodDeliveryService,
    FreeDeliveryAbove,
    InMemoryPartners,
    InMemoryRestaurants,
    Location,
    MenuItem,
    MixedRestaurantCartError,
    Notifier,
    OrderEvent,
    OrderObserver,
    PercentOffCoupon,
    Restaurant,
    chain,
)


class PrintingObserver(OrderObserver):
    """Stands in for push notifications. print is fine here: this is __main__."""

    def on_event(self, event: OrderEvent) -> None:
        print(f"  [notify {event.customer_id}] {event.order_id} "
              f"{event.kind.value}: {event.status.name} {event.detail}".rstrip())


def seed(restaurants: InMemoryRestaurants, partners: InMemoryPartners) -> None:
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
    partners.add(DeliveryPartner("P3", "Arjun", Location(9, 9)))   # out of range


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    clock = FixedClock(datetime(2026, 10, 16, 19, 30, tzinfo=UTC))
    restaurants, partners = InMemoryRestaurants(), InMemoryPartners()
    seed(restaurants, partners)
    svc = FoodDeliveryService(
        clock=clock, restaurants=restaurants, partners=partners,
        discounts=chain(
            PercentOffCoupon("FEAST20", Decimal(20), cap=Decimal(100),
                             min_item_total=Decimal(300)),
            FreeDeliveryAbove(Decimal(499))),
        notifier=Notifier([PrintingObserver()]))
    home = Location(3, 4)                       # 5 km from Biryani House

    svc.add_to_cart("awanish", "R1", "biryani", 2)
    svc.add_to_cart("awanish", "R1", "jamun")
    try:
        svc.add_to_cart("awanish", "R2", "dosa")
    except MixedRestaurantCartError as e:
        print(f"expected: {e}")

    bill = svc.quote("awanish", home, "feast20")
    print(f"bill: food {bill.item_total} - discount {bill.discount} "
          f"+ delivery {bill.delivery_fee} + tax {bill.tax} = {bill.total}")

    order = svc.place_order("awanish", home, "key-001", "FEAST20")
    retry = svc.place_order("awanish", home, "key-001", "FEAST20")
    print(f"placed {order.order_id}; retry with same key -> {retry.order_id}, "
          f"eta {order.eta:%H:%M}")

    svc.accept(order.order_id)                  # offered to Ravi, the nearest
    clock.advance(seconds=31)                   # Ravi never answers
    svc.tick()                                  # offer moves to Meena
    svc.partner_accept(order.order_id, "P2")
    svc.start_preparing(order.order_id)
    svc.mark_ready(order.order_id)
    svc.pick_up(order.order_id, "P2")
    clock.advance(minutes=18)
    svc.deliver(order.order_id, "P2")
    print("history:", " -> ".join(c.status.name for c in order.history))

    svc.add_to_cart("awanish", "R1", "paneer", 2)
    second = svc.place_order("awanish", home, "key-002")
    svc.accept(second.order_id)
    svc.start_preparing(second.order_id)
    svc.cancel(second.order_id)
    print(f"cancelled {second.order_id} while PREPARING: "
          f"paid {second.bill.total}, refund {second.refund}")


if __name__ == "__main__":
    main()
