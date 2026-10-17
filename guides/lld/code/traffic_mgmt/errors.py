"""Domain errors for the city traffic management system.

One root, TrafficError, so a caller can catch "anything this domain raises"
in one clause. Each subclass names one failure with one recovery.
"""


class TrafficError(Exception):
    """Base of every error the traffic domain can raise."""


class InvalidConfigError(TrafficError):
    """A config dataclass was built with an impossible value."""


class InvalidPlanError(TrafficError):
    """A timing plan cannot be executed safely (too short, bad offset...)."""


class IllegalTransitionError(TrafficError):
    """A phase change that the transition table does not allow."""


class UnknownIntersectionError(TrafficError):
    """No intersection or controller with that id."""


class UnknownLinkError(TrafficError):
    """No road link with that id."""


class NoRouteError(TrafficError):
    """No open path between two intersections."""


class PreemptionConflictError(TrafficError):
    """The intersection is already preempted for the crossing axis."""


class SignalFaultError(TrafficError):
    """The controller is in fault flash and accepts no commands but a reset."""


class CommunicationLostError(TrafficError):
    """The link between the centre and a controller is down."""


class EmergencyDispatchError(TrafficError):
    """An emergency run cannot be dispatched (duplicate id, bad speed...)."""
