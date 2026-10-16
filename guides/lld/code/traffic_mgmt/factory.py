"""Composition root: wire one city from a road network.

Every collaborator is built here and handed in through constructors, so no
class below reaches out to create its own dependencies.
"""
from dataclasses import dataclass

from .clock import ManualClock
from .comms import InMemoryComms, Uplink
from .config import ControllerConfig, TmcConfig
from .controller import IntersectionController
from .events import EventBus
from .network import RoadNetwork
from .sensors import ApproachQueues
from .simulation import TrafficSimulation
from .tmc import TrafficManagementCenter


@dataclass(frozen=True)
class City:
    clock: ManualClock
    network: RoadNetwork
    comms: InMemoryComms
    bus: EventBus
    tmc: TrafficManagementCenter
    controllers: dict[str, IntersectionController]
    uplinks: dict[str, Uplink]
    queues: dict[str, ApproachQueues]
    sim: TrafficSimulation


def build_city(
    network: RoadNetwork,
    clock: ManualClock,
    controller_config: ControllerConfig = ControllerConfig(),
    tmc_config: TmcConfig = TmcConfig(),
) -> City:
    comms = InMemoryComms()
    bus = EventBus()
    tmc = TrafficManagementCenter(network, comms, clock, tmc_config)
    bus.subscribe(tmc)
    controllers: dict[str, IntersectionController] = {}
    uplinks: dict[str, Uplink] = {}
    queues: dict[str, ApproachQueues] = {}
    for iid in network.intersections():
        queues[iid] = ApproachQueues(controller_config.discharge)
        uplinks[iid] = Uplink(iid, comms, bus, controller_config.failsafe.telemetry_buffer)
        controllers[iid] = IntersectionController(
            iid, clock, queues[iid], uplinks[iid], controller_config
        )
        tmc.register(controllers[iid])
    sim = TrafficSimulation(clock, tmc, controllers, queues)
    return City(clock, network, comms, bus, tmc, controllers, uplinks, queues, sim)
