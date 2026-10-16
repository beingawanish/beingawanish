"""Ride-sharing: dispatch, trip lifecycle, surge pricing, ratings."""
from .clock import Clock, ManualClock, SystemClock
from .config import RideConfig
from .dispatch import Dispatcher
from .errors import (
    DriverBusyError,
    DriverNotFoundError,
    DuplicateIdError,
    IllegalTransitionError,
    InvalidInputError,
    NotFoundError,
    OfferExpiredError,
    OfferNotFoundError,
    RatingError,
    RideSharingError,
    RiderNotFoundError,
    TripNotFoundError,
)
from .events import EventKind, EventPublisher, RecordingObserver, TripEvent, TripObserver
from .lifecycle import ALLOWED, can_transition, transition
from .matching import MatchingStrategy, NearestDriverStrategy, RatingWeightedStrategy
from .models import (
    CancelledBy,
    Driver,
    DriverStatus,
    FareQuote,
    Location,
    Offer,
    RatingBook,
    Rider,
    Trip,
    TripStatus,
)
from .pricing import (
    CancellationPolicy,
    FareStrategy,
    GracePeriodCancellation,
    StandardFare,
    SupplyDemandSurge,
    SurgePolicy,
)
from .repositories import (
    DriverRepository,
    InMemoryDrivers,
    InMemoryRiders,
    InMemoryTrips,
    RiderRepository,
    TripRepository,
)
from .service import RideService
from .spatial import GridIndex, SpatialIndex

__all__ = [
    "DriverBusyError", "DriverNotFoundError", "DuplicateIdError",
    "IllegalTransitionError", "InvalidInputError", "NotFoundError",
    "OfferExpiredError", "OfferNotFoundError", "RatingError",
    "RideSharingError", "RiderNotFoundError", "TripNotFoundError",
    "CancelledBy", "Driver", "DriverStatus", "FareQuote", "Location",
    "Offer", "RatingBook", "Rider", "Trip", "TripStatus",
    "CancellationPolicy", "FareStrategy", "GracePeriodCancellation",
    "StandardFare", "SupplyDemandSurge", "SurgePolicy", "DriverRepository",
    "InMemoryDrivers", "InMemoryRiders", "InMemoryTrips", "RiderRepository",
    "TripRepository", "Clock", "ManualClock", "SystemClock", "RideConfig",
    "Dispatcher", "EventKind", "EventPublisher", "RecordingObserver",
    "TripEvent", "TripObserver", "ALLOWED", "can_transition", "transition",
    "MatchingStrategy", "NearestDriverStrategy", "RatingWeightedStrategy",
    "RideService", "GridIndex", "SpatialIndex",
]
