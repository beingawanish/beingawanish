"""Runnable slice: a green wave, adaptive timing, an incident, an ambulance,
a comms outage and a fault flash, on one deterministic clock.

    python3 -m traffic_mgmt
"""
import logging

from . import (
    AdaptivePlan,
    AdaptiveTuning,
    Axis,
    ControlMode,
    CycleStarted,
    FixedTimePlan,
    GreenWaveDesigner,
    Link,
    ManualClock,
    ModeChanged,
    Phase,
    PhaseChanged,
    RecordingListener,
    RoadNetwork,
    SafetyTimings,
    TimeOfDayPlan,
    build_city,
)

START = 7 * 3600  # 07:00 on day zero


def build_network() -> RoadNetwork:
    """Main Street runs north through A, B, C. D is a side-street detour."""
    net = RoadNetwork()
    for iid in ("A", "B", "C", "D"):
        net.add_intersection(iid)
    net.add_link(Link("A-B", "A", "B", 300, Axis.NS))
    net.add_link(Link("B-C", "B", "C", 450, Axis.NS))
    net.add_link(Link("A-D", "A", "D", 400, Axis.EW))
    net.add_link(Link("D-C", "D", "C", 400, Axis.NS))
    return net


def main() -> None:
    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(name)s: %(message)s")
    clock = ManualClock(START)
    city = build_city(build_network(), clock)
    seen = RecordingListener()
    city.bus.subscribe(seen)

    def t() -> int:
        return clock.now() - START

    print("== 1. green wave on Main Street (15 m/s, 60 s cycle) ==")
    wave = GreenWaveDesigner(city.network, SafetyTimings()).design(["A-B", "B-C"], 15, 60, 25)
    print("offsets:", {iid: plan.offset for iid, plan in wave.items()})
    city.tmc.set_plans(wave)
    city.sim.run(150)
    starts = [(e.intersection_id, e.at - START) for e in seen.events()
              if isinstance(e, PhaseChanged) and e.phase is Phase.NS_GREEN
              and e.intersection_id in wave and e.at - START >= 60]
    print("NS green starts after sync:", starts)

    print("== 2. adaptive peak plan at D ==")
    peak = TimeOfDayPlan([(0, FixedTimePlan(15, 15, "night")),
                          (6 * 3600, AdaptivePlan(AdaptiveTuning())),
                          (20 * 3600, FixedTimePlan(15, 15, "night"))])
    city.tmc.set_plan("D", peak)
    city.sim.add_arrivals("D", Axis.NS, 12)
    city.sim.add_arrivals("D", Axis.EW, 3)
    city.sim.run(90)
    for c in seen.events():
        if isinstance(c, CycleStarted) and c.intersection_id == "D" and c.at - START > 150:
            print(f"t={c.at - START} D cycle: queues ns={c.queue_ns} ew={c.queue_ew} "
                  f"-> green ns={c.split.ns}s ew={c.split.ew}s via {c.split.plan}")

    print("== 3. incident closes B-C; ambulance A -> C ==")
    city.tmc.report_incident("B-C", lanes_closed=2)
    route = city.tmc.dispatch_emergency("AMB-7", "A", "C", speed_mps=12)
    print(f"t={t()} route avoids B-C:", route)
    for _ in range(12):
        city.sim.run(10)
        legs = city.tmc.emergency_legs("AMB-7")
        held = {iid: city.controllers[iid].phase.name for iid, _ in legs}
        print(f"t={t()}", [(iid, state.value) for iid, state in legs], held)
        if all(state.value == "released" for _, state in legs):
            break

    print("== 4. comms to B cut for 40 s ==")
    city.comms.sever("B")
    city.sim.run(40)
    print(f"t={t()} B mode={city.controllers['B'].mode.name}, "
          f"centre still thinks {city.tmc.status('B').mode.name}, buffered={city.uplinks['B'].buffered}")
    city.comms.restore("B")
    city.sim.run(5)
    modes = [(e.at - START, e.mode.name, e.reason) for e in seen.events()
             if isinstance(e, ModeChanged) and e.intersection_id == "B" and e.at - START > 60]
    print(f"t={t()} after restore, centre sees B {city.tmc.status('B').mode.name}; history: {modes}")

    print("== 5. conflict monitor trips at D ==")
    city.controllers["D"].report_fault("conflict monitor: green-green detected")
    city.sim.run(30)
    print(f"t={t()} D phase={city.controllers['D'].phase.name} mode={city.controllers['D'].mode.name}")
    city.controllers["D"].reset_fault()
    city.sim.run(3)
    d = city.controllers["D"]
    print(f"t={t()} after reset D phase={d.phase.name} mode={d.mode.name}")
    assert d.mode is ControlMode.CENTRAL


if __name__ == "__main__":
    main()
