"""Runnable slice of version 2. Run from the folder holding car_rental/ and
car_rental_v2/:   python3 -m car_rental_v2

A FixedClock and the in-memory gateway make every run print the same thing,
apart from the random reservation ids.
"""
import logging
from datetime import date

from car_rental import FixedClock, VehicleCategory

from . import (
    Branch,
    Damage,
    DamageKind,
    InMemoryPaymentGateway,
    InspectionReport,
    LoyaltyTier,
    build_desk,
)


def show_quote(desk, trip) -> None:
    for line in desk.quote(trip.reservation_id).lines:
        print(f"    {line.label:<34}{line.amount:>9.2f}")
    print(f"    {'locked total':<34}{trip.quoted_total:>9.2f}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    clock = FixedClock(date(2026, 10, 15))
    gateway = InMemoryPaymentGateway()
    desk = build_desk(clock=clock, gateway=gateway,
                      branches=[Branch("DT", "Downtown"), Branch("AP", "Airport")],
                      loyalty={"Awanish Singh": LoyaltyTier.GOLD})
    desk.add_vehicle("ECO-01", VehicleCategory.ECONOMY, "Toyota", "Corolla", 2023, "DT")
    desk.add_vehicle("ECO-02", VehicleCategory.ECONOMY, "Honda", "Civic", 2022, "DT")
    desk.add_ev("EV-01", VehicleCategory.LUXURY, "Polestar", "2", 2025, "DT",
                battery_kwh=78.0, charge_pct=90)

    print("1. Book ECO-02 Oct 23-26, then ECO-01 the same days, one-way DT -> AP")
    desk.book("ECO-02", "Shyam Miyatra", date(2026, 10, 23), date(2026, 10, 26), "DT")
    trip = desk.book("ECO-01", "Awanish Singh", date(2026, 10, 23),
                     date(2026, 10, 26), "DT", "AP")
    show_quote(desk, trip)

    print("2. Pick up on Oct 23: deposit hold")
    clock.advance(8)
    hold = desk.pick_up(trip.reservation_id,
                        walkaround=[Damage(DamageKind.SCRATCH, "rear bumper")])
    print(f"    held ${hold.held:.2f} ({hold.hold_id}), "
          f"car is {desk.status('ECO-01').state.name}")

    print("3. Return at AP on Oct 27 (a day late) with one new dent")
    clock.advance(4)
    desk.return_vehicle(trip.reservation_id)
    report = InspectionReport(frozenset({
        Damage(DamageKind.SCRATCH, "rear bumper"),     # known at pickup: free
        Damage(DamageKind.DENT, "front left door"),    # new: charged
    }))
    summary = desk.complete_inspection(trip.reservation_id, report)
    for line in summary.extras:
        print(f"    {line.label:<34}{line.amount:>9.2f}")
    s = summary.settlement
    print(f"    final ${s.final:.2f}: captured ${s.captured:.2f}, "
          f"released ${s.released:.2f}, extra charge ${s.extra_charged:.2f}")
    status = desk.status("ECO-01")
    print(f"    ECO-01 is now {status.state.name} at {status.branch_id}")

    print("4. The EV comes back at 35%")
    ev_trip = desk.book("EV-01", "Jacob", date(2026, 10, 27), date(2026, 10, 29), "DT")
    desk.pick_up(ev_trip.reservation_id)
    clock.advance(2)
    desk.return_vehicle(ev_trip.reservation_id)
    ev_summary = desk.complete_inspection(ev_trip.reservation_id,
                                          InspectionReport(charge_pct=35))
    for line in ev_summary.extras:
        print(f"    {line.label:<34}{line.amount:>9.2f}")
    print(f"    EV-01 is now {ev_summary.next_state.name}")
    desk.finish_charging("EV-01", 95)
    print(f"    after charging: {desk.status('EV-01').state.name}")

    print("5. Money that actually moved through the gateway")
    for op in gateway.executed:
        print(f"    {op}")


if __name__ == "__main__":
    main()
