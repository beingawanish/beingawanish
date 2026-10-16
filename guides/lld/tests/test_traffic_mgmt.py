"""Tests for city traffic management. Every test runs on a ManualClock."""
import logging
import sys
import threading
import unittest
from fractions import Fraction
from pathlib import Path

# The package lives in code/ beside tests/. A flat layout needs no shim.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))

from traffic_mgmt import (  # noqa: E402
    TRANSITIONS,
    AdaptivePlan,
    AdaptiveTuning,
    ApproachQueues,
    Axis,
    CommunicationLostError,
    ControlMode,
    ControllerConfig,
    CoordinatedPlan,
    CycleContext,
    CycleStarted,
    DischargeConfig,
    EmergencyDispatchError,
    EventBus,
    FailsafeConfig,
    FixedTimePlan,
    GreenSplit,
    GreenWaveDesigner,
    IllegalTransitionError,
    InMemoryComms,
    IntersectionController,
    InvalidConfigError,
    InvalidPlanError,
    LegState,
    Link,
    ManualClock,
    NoRouteError,
    Phase,
    PhaseChanged,
    PreemptionConflictError,
    RecordingListener,
    RoadNetwork,
    SafetyTimings,
    SignalFaultError,
    TelemetryListener,
    TimeOfDayPlan,
    TmcConfig,
    UnknownLinkError,
    Uplink,
    build_city,
)

SAFETY = SafetyTimings()  # min_green 7, yellow 3, all_red 2


def setUpModule() -> None:
    logging.getLogger("traffic_mgmt").setLevel(logging.CRITICAL)


def make_controller(config: ControllerConfig = ControllerConfig()):
    """One controller with a recording sink and a manual clock."""
    clock = ManualClock()
    queues = ApproachQueues(config.discharge)
    sink = RecordingListener()
    bus = EventBus()
    bus.subscribe(sink)
    ctrl = IntersectionController("X", clock, queues, bus, config)
    return ctrl, clock, queues, sink


def run(ctrl: IntersectionController, clock: ManualClock, seconds: int,
        heartbeat_every: int | None = None) -> None:
    for _ in range(seconds):
        clock.advance(1)
        ctrl.step()
        if heartbeat_every and clock.now() % heartbeat_every == 0:
            ctrl.heartbeat()


def phases(sink: RecordingListener) -> list[Phase]:
    return [e.phase for e in sink.events() if isinstance(e, PhaseChanged)]


def corridor_network() -> RoadNetwork:
    """A -> B -> C on the NS axis, plus a detour A -> D -> C."""
    net = RoadNetwork()
    for iid in ("A", "B", "C", "D"):
        net.add_intersection(iid)
    net.add_link(Link("A-B", "A", "B", 300, Axis.NS))
    net.add_link(Link("B-C", "B", "C", 450, Axis.NS))
    net.add_link(Link("A-D", "A", "D", 400, Axis.EW))
    net.add_link(Link("D-C", "D", "C", 400, Axis.NS))
    return net


class ConfigTests(unittest.TestCase):
    def test_non_positive_safety_timing_rejected(self):
        with self.assertRaises(InvalidConfigError):
            SafetyTimings(yellow=0)

    def test_bool_is_not_a_duration(self):
        with self.assertRaises(InvalidConfigError):
            SafetyTimings(all_red=True)

    def test_adaptive_base_above_max_rejected(self):
        with self.assertRaises(InvalidConfigError):
            AdaptiveTuning(base_green=70, max_green=60)

    def test_fallback_below_min_green_rejected(self):
        with self.assertRaises(InvalidConfigError):
            ControllerConfig(failsafe=FailsafeConfig(fallback_ns_green=5))


class TimingStrategyTests(unittest.TestCase):
    def ctx(self, now=0, ns=0, ew=0, cap_ns=Fraction(1), cap_ew=Fraction(1)):
        return CycleContext(now, ns, ew, cap_ns, cap_ew)

    def test_fixed_plan_ignores_queues(self):
        plan = FixedTimePlan(20, 15)
        self.assertEqual(plan.split(self.ctx(ns=99)), GreenSplit(20, 15, "fixed"))

    def test_adaptive_grows_with_queue(self):
        split = AdaptivePlan(AdaptiveTuning()).split(self.ctx(ns=12, ew=3))
        self.assertEqual((split.ns, split.ew), (34, 16))  # 10 + 2*12, 10 + 2*3

    def test_adaptive_caps_at_max_green(self):
        split = AdaptivePlan(AdaptiveTuning()).split(self.ctx(ns=500))
        self.assertEqual(split.ns, 60)

    def test_lane_closure_stretches_adaptive_green(self):
        split = AdaptivePlan(AdaptiveTuning()).split(self.ctx(ns=10, cap_ns=Fraction(1, 2)))
        self.assertEqual(split.ns, 50)  # 10 + 2*10 / (1/2)

    def test_time_of_day_picks_entry_and_wraps(self):
        night, peak = FixedTimePlan(10, 10, "night"), FixedTimePlan(30, 20, "peak")
        plan = TimeOfDayPlan([(6 * 3600, peak), (20 * 3600, night)])
        self.assertEqual(plan.split(self.ctx(now=7 * 3600)).plan, "peak")
        self.assertEqual(plan.split(self.ctx(now=21 * 3600)).plan, "night")
        self.assertEqual(plan.split(self.ctx(now=3 * 3600)).plan, "night")  # from yesterday
        self.assertEqual(plan.split(self.ctx(now=86_400 + 7 * 3600)).plan, "peak")  # day two

    def test_time_of_day_rejects_unsorted_entries(self):
        with self.assertRaises(InvalidPlanError):
            TimeOfDayPlan([(100, FixedTimePlan(10, 10)), (50, FixedTimePlan(10, 10))])

    def test_coordinated_on_beat_runs_nominal_cycle(self):
        plan = CoordinatedPlan(60, 20, 25, SAFETY)
        self.assertEqual(plan.split(self.ctx(now=80)), GreenSplit(25, 25, "coordinated"))  # 60 - 25 - 10

    def test_coordinated_off_beat_lands_next_start_on_beat(self):
        plan = CoordinatedPlan(60, 20, 25, SAFETY)
        for now in range(0, 200, 7):
            split = plan.split(self.ctx(now=now))
            next_start = now + split.ns + split.ew + 2 * SAFETY.clearance
            self.assertEqual((next_start - 20) % 60, 0, now)
            self.assertGreaterEqual(split.ew, SAFETY.min_green)

    def test_coordinated_cycle_too_short_rejected(self):
        with self.assertRaises(InvalidPlanError):
            CoordinatedPlan(40, 0, 25, SAFETY)  # 25 + 7 + 10 = 42 > 40


class ControllerCycleTests(unittest.TestCase):
    def test_boots_in_all_red_then_full_cycle(self):
        ctrl, clock, _, sink = make_controller()
        self.assertIs(ctrl.phase, Phase.ALL_RED)
        run(ctrl, clock, 2 + 20 + 3 + 2 + 20 + 3 + 2)
        self.assertEqual(phases(sink), [
            Phase.NS_GREEN, Phase.NS_YELLOW, Phase.ALL_RED,
            Phase.EW_GREEN, Phase.EW_YELLOW, Phase.ALL_RED, Phase.NS_GREEN,
        ])

    def test_boots_in_local_fallback_mode(self):
        ctrl, *_ = make_controller()
        self.assertIs(ctrl.mode, ControlMode.LOCAL_FALLBACK)

    def test_plan_below_min_green_is_clamped(self):
        ctrl, clock, _, sink = make_controller()
        ctrl.heartbeat()
        ctrl.apply_plan(FixedTimePlan(1, 1, "reckless"))
        run(ctrl, clock, 2)
        cycle = [e for e in sink.events() if isinstance(e, CycleStarted)][0]
        self.assertEqual((cycle.split.ns, cycle.split.ew), (7, 7))

    def test_new_plan_waits_for_cycle_boundary(self):
        ctrl, clock, _, sink = make_controller()
        ctrl.heartbeat()
        run(ctrl, clock, 5)  # NS green under fallback 20/20
        ctrl.apply_plan(FixedTimePlan(9, 9, "new"))
        run(ctrl, clock, 10)
        self.assertIs(ctrl.phase, Phase.NS_GREEN)  # the old 20 s green continues
        run(ctrl, clock, 60, heartbeat_every=5)
        plans = [e.split.plan for e in sink.events() if isinstance(e, CycleStarted)]
        self.assertEqual(plans[0], "local-fixed")
        self.assertEqual(plans[1], "new")

    def test_green_discharges_queue(self):
        ctrl, clock, queues, _ = make_controller()
        queues.arrive(Axis.NS, 5)
        run(ctrl, clock, 2 + 6)  # 6 s of NS green at one car per 2 s
        self.assertEqual(queues.count(Axis.NS), 2)

    def test_illegal_transition_refused(self):
        ctrl, *_ = make_controller()
        with self.assertRaises(IllegalTransitionError):
            ctrl.reset_fault()  # not flashing


class FailsafeTests(unittest.TestCase):
    def test_heartbeat_timeout_falls_back_and_heartbeat_restores(self):
        ctrl, clock, _, _ = make_controller()
        ctrl.heartbeat()
        self.assertIs(ctrl.mode, ControlMode.CENTRAL)
        run(ctrl, clock, 15)
        self.assertIs(ctrl.mode, ControlMode.CENTRAL)  # exactly at the limit
        run(ctrl, clock, 1)
        self.assertIs(ctrl.mode, ControlMode.LOCAL_FALLBACK)
        ctrl.heartbeat()
        self.assertIs(ctrl.mode, ControlMode.CENTRAL)

    def test_fallback_uses_local_plan_not_central(self):
        ctrl, clock, _, sink = make_controller()
        ctrl.heartbeat()
        ctrl.apply_plan(FixedTimePlan(40, 40, "central"))
        run(ctrl, clock, 2)
        run(ctrl, clock, 100)  # no heartbeats: fallback by the next cycle
        plans = [e.split.plan for e in sink.events() if isinstance(e, CycleStarted)]
        self.assertEqual(plans[0], "central")
        self.assertEqual(plans[-1], "local-fixed")

    def test_fault_flashes_immediately_and_holds(self):
        ctrl, clock, _, _ = make_controller()
        run(ctrl, clock, 5)
        ctrl.report_fault("green-green")
        run(ctrl, clock, 500)
        self.assertIs(ctrl.phase, Phase.FLASHING_RED)
        self.assertIs(ctrl.mode, ControlMode.FLASHING)

    def test_flashing_controller_refuses_preemption(self):
        ctrl, *_ = make_controller()
        ctrl.report_fault("green-green")
        with self.assertRaises(SignalFaultError):
            ctrl.preempt(Axis.NS, "AMB")

    def test_reset_goes_through_all_red(self):
        ctrl, clock, _, sink = make_controller()
        ctrl.report_fault("green-green")
        ctrl.reset_fault()
        run(ctrl, clock, 2)
        self.assertEqual(phases(sink)[-3:], [Phase.FLASHING_RED, Phase.ALL_RED, Phase.NS_GREEN])


class PreemptionTests(unittest.TestCase):
    def test_same_axis_green_is_held(self):
        ctrl, clock, _, _ = make_controller()
        run(ctrl, clock, 3)  # NS green
        ctrl.preempt(Axis.NS, "AMB")
        run(ctrl, clock, 100)
        self.assertIs(ctrl.phase, Phase.PREEMPT_NS)

    def test_cross_green_is_cleared_through_yellow_and_all_red(self):
        ctrl, clock, _, sink = make_controller()
        run(ctrl, clock, 3)  # NS green
        ctrl.preempt(Axis.EW, "AMB")
        self.assertIs(ctrl.phase, Phase.NS_YELLOW)
        run(ctrl, clock, 5)
        self.assertEqual(phases(sink)[-3:], [Phase.NS_YELLOW, Phase.ALL_RED, Phase.PREEMPT_EW])

    def test_release_returns_through_yellow(self):
        ctrl, clock, _, _ = make_controller()
        run(ctrl, clock, 3)
        ctrl.preempt(Axis.NS, "AMB")
        self.assertTrue(ctrl.release("AMB"))
        self.assertIs(ctrl.phase, Phase.NS_YELLOW)
        self.assertFalse(ctrl.release("AMB"))  # idempotent

    def test_conflicting_axis_rejected(self):
        ctrl, clock, _, _ = make_controller()
        run(ctrl, clock, 3)
        ctrl.preempt(Axis.NS, "AMB")
        with self.assertRaises(PreemptionConflictError):
            ctrl.preempt(Axis.EW, "FIRE")

    def test_hold_lasts_until_last_vehicle_releases(self):
        ctrl, clock, _, _ = make_controller()
        run(ctrl, clock, 3)
        ctrl.preempt(Axis.NS, "AMB")
        ctrl.preempt(Axis.NS, "FIRE")
        ctrl.release("AMB")
        self.assertIs(ctrl.phase, Phase.PREEMPT_NS)
        ctrl.release("FIRE")
        self.assertIs(ctrl.phase, Phase.NS_YELLOW)

    def test_controller_auto_releases_a_forgotten_hold(self):
        ctrl, clock, _, _ = make_controller()
        run(ctrl, clock, 3)
        ctrl.preempt(Axis.NS, "AMB")
        run(ctrl, clock, 120)
        self.assertIs(ctrl.phase, Phase.NS_YELLOW)
        self.assertEqual(ctrl.preempted_by, frozenset())


class QueueAndNetworkTests(unittest.TestCase):
    def test_half_capacity_halves_discharge(self):
        queues = ApproachQueues(DischargeConfig())
        queues.arrive(Axis.EW, 10)
        queues.set_capacity(Axis.EW, Fraction(1, 2))
        queues.discharge(Axis.EW, 8)
        self.assertEqual(queues.count(Axis.EW), 8)

    def test_negative_arrivals_rejected(self):
        with self.assertRaises(ValueError):
            ApproachQueues(DischargeConfig()).arrive(Axis.NS, -1)

    def test_shortest_route_and_closure_detour(self):
        net = corridor_network()
        self.assertEqual([lk.link_id for lk in net.shortest_route("A", "C")], ["A-B", "B-C"])
        net.set_lanes_closed("B-C", 2)
        self.assertEqual([lk.link_id for lk in net.shortest_route("A", "C")], ["A-D", "D-C"])

    def test_partial_closure_keeps_link_open(self):
        net = corridor_network()
        self.assertEqual(net.set_lanes_closed("B-C", 1), Fraction(1, 2))
        self.assertTrue(net.is_open("B-C"))

    def test_no_route_raises(self):
        net = corridor_network()
        with self.assertRaises(NoRouteError):
            net.shortest_route("C", "A")  # links are one-way

    def test_unknown_link_raises(self):
        with self.assertRaises(UnknownLinkError):
            corridor_network().set_lanes_closed("Z-Z", 1)


class GreenWaveTests(unittest.TestCase):
    def test_offsets_follow_travel_time(self):
        plans = GreenWaveDesigner(corridor_network(), SAFETY).design(["A-B", "B-C"], 15, 60, 25)
        self.assertEqual({iid: p.offset for iid, p in plans.items()}, {"A": 0, "B": 20, "C": 50})

    def test_broken_corridor_rejected(self):
        with self.assertRaises(InvalidPlanError):
            GreenWaveDesigner(corridor_network(), SAFETY).design(["A-B", "D-C"], 15, 60, 25)

    def test_city_falls_into_step_after_one_cycle(self):
        city = build_city(corridor_network(), ManualClock(7 * 3600))
        seen = RecordingListener()
        city.bus.subscribe(seen)
        wave = GreenWaveDesigner(city.network, SAFETY).design(["A-B", "B-C"], 15, 60, 25)
        city.tmc.set_plans(wave)
        city.sim.run(300)
        for iid, plan in wave.items():
            starts = [e.at for e in seen.events() if isinstance(e, PhaseChanged)
                      and e.intersection_id == iid and e.phase is Phase.NS_GREEN]
            self.assertTrue(all((s - plan.offset) % 60 == 0 for s in starts[1:]), (iid, starts))

    def test_wave_resyncs_after_preemption(self):
        city = build_city(corridor_network(), ManualClock(0))
        seen = RecordingListener()
        city.bus.subscribe(seen)
        city.tmc.set_plans(GreenWaveDesigner(city.network, SAFETY).design(["A-B"], 15, 60, 25))
        city.sim.run(100)
        city.controllers["B"].preempt(Axis.EW, "AMB")
        city.sim.run(30)
        city.controllers["B"].release("AMB")
        city.sim.run(200)
        starts = [e.at for e in seen.events() if isinstance(e, PhaseChanged)
                  and e.intersection_id == "B" and e.phase is Phase.NS_GREEN and e.at > 130]
        self.assertTrue(starts)
        self.assertTrue(all((s - 20) % 60 == 0 for s in starts[1:]), starts)


class CentreTests(unittest.TestCase):
    def setUp(self):
        self.clock = ManualClock(0)
        self.city = build_city(corridor_network(), self.clock)

    def test_heartbeat_interval_must_beat_timeout(self):
        with self.assertRaises(InvalidConfigError):
            build_city(corridor_network(), ManualClock(), tmc_config=TmcConfig(heartbeat_interval=15))

    def test_plan_set_during_outage_is_delivered_on_restore(self):
        self.city.comms.sever("B")
        self.assertFalse(self.city.tmc.set_plan("B", FixedTimePlan(30, 30, "late")))
        self.city.sim.run(60)
        self.city.comms.restore("B")
        self.city.sim.run(90)
        self.assertEqual(self.city.tmc.status("B").mode, ControlMode.CENTRAL)
        seen = RecordingListener()
        self.city.bus.subscribe(seen)
        self.city.sim.run(90)
        plans = {e.split.plan for e in seen.events() if isinstance(e, CycleStarted)
                 and e.intersection_id == "B"}
        self.assertEqual(plans, {"late"})

    def test_outage_telemetry_is_buffered_then_flushed(self):
        self.city.sim.run(10)
        self.city.comms.sever("B")
        self.city.sim.run(40)
        self.assertIs(self.city.controllers["B"].mode, ControlMode.LOCAL_FALLBACK)
        self.assertIs(self.city.tmc.status("B").mode, ControlMode.CENTRAL)  # stale view
        self.assertGreater(self.city.uplinks["B"].buffered, 0)
        self.city.comms.restore("B")
        self.city.sim.run(5)
        self.assertEqual(self.city.uplinks["B"].buffered, 0)
        self.assertIs(self.city.tmc.status("B").mode, ControlMode.CENTRAL)

    def test_uplink_drops_oldest_when_full(self):
        comms, sink = InMemoryComms(), RecordingListener()
        bus = EventBus()
        bus.subscribe(sink)
        uplink = Uplink("X", comms, bus, capacity=2)
        comms.sever("X")
        for at in range(3):
            uplink.send(PhaseChanged("X", at, Phase.ALL_RED))
        comms.restore("X")
        uplink.send(PhaseChanged("X", 3, Phase.NS_GREEN))
        self.assertEqual([e.at for e in sink.events()], [1, 2, 3])
        self.assertEqual(uplink.dropped, 1)

    def test_emergency_run_preempts_ahead_and_releases_behind(self):
        self.city.sim.run(30)
        route = self.city.tmc.dispatch_emergency("AMB", "A", "C", 15)
        self.assertEqual(route, ["B", "C"])  # ETAs: B at 50, C at 80
        self.city.sim.run(1)
        self.assertEqual(self.city.tmc.emergency_legs("AMB"),
                         [("B", LegState.HELD), ("C", LegState.PENDING)])
        self.city.sim.run(29)  # t=60: C preempted, B still held until 55
        self.assertEqual(self.city.tmc.emergency_legs("AMB"),
                         [("B", LegState.RELEASED), ("C", LegState.HELD)])
        self.city.sim.run(30)
        self.assertEqual(self.city.tmc.emergency_legs("AMB"),
                         [("B", LegState.RELEASED), ("C", LegState.RELEASED)])

    def test_conflicting_run_waits_its_turn(self):
        self.city.sim.run(30)
        self.city.controllers["B"].preempt(Axis.EW, "FIRE")
        self.city.tmc.dispatch_emergency("AMB", "A", "B", 15)
        self.city.sim.run(5)
        self.assertEqual(self.city.tmc.emergency_legs("AMB"), [("B", LegState.PENDING)])
        self.city.controllers["B"].release("FIRE")
        self.city.sim.run(1)
        self.assertEqual(self.city.tmc.emergency_legs("AMB"), [("B", LegState.HELD)])

    def test_duplicate_dispatch_rejected(self):
        self.city.tmc.dispatch_emergency("AMB", "A", "C", 15)
        with self.assertRaises(EmergencyDispatchError):
            self.city.tmc.dispatch_emergency("AMB", "A", "C", 15)

    def test_incident_reroutes_and_informs_controller(self):
        self.city.tmc.report_incident("B-C", 2)
        self.assertEqual(self.city.tmc.dispatch_emergency("AMB", "A", "C", 15), ["D", "C"])
        self.city.tmc.report_incident("A-B", 1)
        self.assertEqual(self.city.controllers["B"]._queues.capacity(Axis.NS), Fraction(1, 2))

    def test_unreachable_command_raises_for_direct_callers(self):
        self.city.comms.sever("A")
        with self.assertRaises(CommunicationLostError):
            self.city.tmc._send("A", lambda: None)


class ObserverTests(unittest.TestCase):
    def test_failing_listener_does_not_stop_others(self):
        class Broken(TelemetryListener):
            def on_event(self, event):
                raise RuntimeError("dashboard down")

        bus, good = EventBus(), RecordingListener()
        bus.subscribe(Broken())
        bus.subscribe(good)
        bus.send(PhaseChanged("X", 0, Phase.ALL_RED))
        self.assertEqual(len(good.events()), 1)


class ConcurrencyTests(unittest.TestCase):
    def test_commands_from_many_threads_never_break_the_table(self):
        city = build_city(corridor_network(), ManualClock(0))
        seen = RecordingListener()
        city.bus.subscribe(seen)
        errors: list[BaseException] = []

        def hammer(n: int) -> None:
            try:
                ctrl = city.controllers["B"]
                for i in range(200):
                    axis = Axis.NS if (i + n) % 2 else Axis.EW
                    try:
                        ctrl.preempt(axis, f"V{n}")
                    except PreemptionConflictError:
                        pass
                    city.sim.add_arrivals("B", axis, 1)
                    ctrl.release(f"V{n}")
                    city.tmc.set_plan("B", FixedTimePlan(10 + i % 5, 10, "churn"))
            except BaseException as exc:  # surface any failure to the main thread
                errors.append(exc)

        workers = [threading.Thread(target=hammer, args=(n,)) for n in range(4)]
        workers.append(threading.Thread(target=city.sim.run, args=(600,)))
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        self.assertEqual(errors, [])
        trail = [e.phase for e in seen.events()
                 if isinstance(e, PhaseChanged) and e.intersection_id == "B"]
        for before, after in zip(trail, trail[1:]):
            self.assertIn(after, TRANSITIONS[before], f"{before} -> {after}")


if __name__ == "__main__":
    unittest.main()
