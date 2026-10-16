"""Version 2, feature 3: the vehicle state machine and post-return inspection."""
import unittest
from datetime import date

from car_rental import FixedClock, VehicleCategory
from car_rental_v2 import (
    TRANSITIONS,
    Branch,
    Damage,
    DamageKind,
    InMemoryPaymentGateway,
    InMemoryStatuses,
    InspectionReport,
    InvalidTransitionError,
    RentalStageError,
    VehicleLifecycle,
    VehicleNotReadyError,
    VehicleState,
    build_desk,
)

TODAY = date(2026, 10, 15)
END = date(2026, 10, 17)
SCRATCH = Damage(DamageKind.SCRATCH, "rear bumper")
DENT = Damage(DamageKind.DENT, "front left door")


def make_desk():
    clock = FixedClock(TODAY)
    desk = build_desk(clock=clock, gateway=InMemoryPaymentGateway(),
                      branches=[Branch("DT", "Downtown")])
    desk.add_vehicle("ECO-01", VehicleCategory.ECONOMY, "Toyota", "Corolla", 2023, "DT")
    return desk, clock


def rent_and_return(desk, clock, walkaround=()):
    trip = desk.book("ECO-01", "Jacob", clock.today(),
                     date.fromordinal(clock.today().toordinal() + 2), "DT")
    desk.pick_up(trip.reservation_id, walkaround)
    clock.advance(2)
    desk.return_vehicle(trip.reservation_id)
    return trip


class StateMachineTests(unittest.TestCase):
    def setUp(self):
        self.clock = FixedClock(TODAY)
        self.lifecycle = VehicleLifecycle(InMemoryStatuses(), self.clock)
        self.lifecycle.register("ECO-01", "DT")

    def test_every_state_has_a_row_and_retired_is_terminal(self):
        self.assertEqual(set(TRANSITIONS), set(VehicleState))
        self.assertEqual(TRANSITIONS[VehicleState.RETIRED], frozenset())

    def test_illegal_move_raises(self):
        self.lifecycle.transition("ECO-01", VehicleState.ON_RENT, "pickup")
        with self.assertRaises(InvalidTransitionError):
            self.lifecycle.transition("ECO-01", VehicleState.AVAILABLE, "skip inspection")

    def test_history_records_date_and_reason(self):
        self.lifecycle.transition("ECO-01", VehicleState.MAINTENANCE, "brakes")
        last = self.lifecycle.status("ECO-01").history[-1]
        self.assertEqual((last.on, last.from_state, last.to_state, last.reason),
                         (TODAY, VehicleState.AVAILABLE, VehicleState.MAINTENANCE, "brakes"))


class MaintenanceTests(unittest.TestCase):
    def test_maintenance_blocks_search_and_pickup_until_finished(self):
        desk, _ = make_desk()
        trip = desk.book("ECO-01", "Jacob", TODAY, END, "DT")
        desk.send_to_maintenance("ECO-01", "warning light")
        self.assertEqual(desk.search(VehicleCategory.ECONOMY, END,
                                     date(2026, 10, 20), "DT"), [])
        with self.assertRaises(VehicleNotReadyError):
            desk.pick_up(trip.reservation_id)
        desk.finish_maintenance("ECO-01")
        desk.pick_up(trip.reservation_id)

    def test_retired_car_cannot_be_booked(self):
        desk, _ = make_desk()
        desk.retire("ECO-01")
        with self.assertRaises(VehicleNotReadyError):
            desk.book("ECO-01", "Jacob", TODAY, END, "DT")


class InspectionTests(unittest.TestCase):
    def test_damage_seen_at_pickup_is_not_charged(self):
        desk, clock = make_desk()
        trip = rent_and_return(desk, clock, walkaround=[SCRATCH])
        summary = desk.complete_inspection(trip.reservation_id,
                                           InspectionReport(frozenset({SCRATCH})))
        self.assertEqual(summary.extras, ())
        self.assertIs(summary.next_state, VehicleState.AVAILABLE)

    def test_new_scratch_is_charged_and_car_stays_available(self):
        desk, clock = make_desk()
        trip = rent_and_return(desk, clock)
        summary = desk.complete_inspection(trip.reservation_id,
                                           InspectionReport(frozenset({SCRATCH})))
        self.assertEqual([x.amount for x in summary.extras], [150.0])
        self.assertIs(summary.next_state, VehicleState.AVAILABLE)

    def test_new_dent_is_charged_and_sends_car_to_maintenance(self):
        desk, clock = make_desk()
        trip = rent_and_return(desk, clock)
        summary = desk.complete_inspection(trip.reservation_id,
                                           InspectionReport(frozenset({DENT})))
        self.assertEqual(summary.final, round(trip.quoted_total + 400.0, 2))
        self.assertIs(summary.next_state, VehicleState.MAINTENANCE)

    def test_repair_clears_the_dent_but_the_scratch_stays_known(self):
        desk, clock = make_desk()
        first = rent_and_return(desk, clock)
        desk.complete_inspection(first.reservation_id,
                                 InspectionReport(frozenset({DENT, SCRATCH})))
        desk.finish_maintenance("ECO-01")
        second = rent_and_return(desk, clock)
        summary = desk.complete_inspection(second.reservation_id,
                                           InspectionReport(frozenset({SCRATCH})))
        self.assertEqual(summary.extras, ())

    def test_inspection_before_return_is_rejected(self):
        desk, _ = make_desk()
        trip = desk.book("ECO-01", "Jacob", TODAY, END, "DT")
        desk.pick_up(trip.reservation_id)
        with self.assertRaises(RentalStageError):
            desk.complete_inspection(trip.reservation_id, InspectionReport())


if __name__ == "__main__":
    unittest.main()
