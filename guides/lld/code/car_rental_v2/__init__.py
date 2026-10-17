"""Car rental version 2: the interview follow-ups, built beside version 1.

Nothing in car_rental/ is edited. Everything here extends it: a subclass of
Vehicle, an implementation of PricingStrategy, subclasses of RentalError, and
new classes that call the v1 RentalService.
"""
from .branches import BranchNetwork, InMemoryTrips, OneWayFeeRule, TripRepository
from .config import (
    BranchConfig,
    EvConfig,
    InspectionConfig,
    PaymentConfig,
    PricingRulesConfig,
    V2Config,
)
from .desk import RentalDesk, ReturnSummary
from .errors import (
    BranchMismatchError,
    GatewayTimeoutError,
    IdempotencyConflictError,
    InvalidTransitionError,
    PaymentError,
    PaymentStateError,
    RentalStageError,
    TripNotFoundError,
    UnknownBranchError,
    VehicleNotReadyError,
)
from .ev import LowChargeRule, ReturnRule
from .inspection import DamageAssessment, DamageInspector
from .lifecycle import TRANSITIONS, InMemoryStatuses, StatusRepository, VehicleLifecycle
from .models import (
    Branch,
    Damage,
    DamageKind,
    ElectricVehicle,
    InspectionReport,
    LoyaltyTier,
    PriceLine,
    Quote,
    Transition,
    Trip,
    TripStage,
    VehicleState,
    VehicleStatus,
)
from .payments import (
    InMemoryPaymentGateway,
    PaymentGateway,
    PaymentRecord,
    PaymentService,
    Settlement,
)
from .pricing_rules import (
    FleetUtilisation,
    InMemoryLoyalty,
    LongRentalDiscount,
    LoyaltyDirectory,
    LoyaltyDiscount,
    PricingContext,
    PricingRule,
    RuleChainPricing,
    SurgeRule,
    UtilisationSource,
    WeekendRule,
)
from .wiring import build_desk

__all__ = [
    "BranchNetwork", "InMemoryTrips", "OneWayFeeRule", "TripRepository",
    "BranchConfig", "EvConfig", "InspectionConfig", "PaymentConfig",
    "PricingRulesConfig", "V2Config",
    "RentalDesk", "ReturnSummary",
    "BranchMismatchError", "GatewayTimeoutError", "IdempotencyConflictError",
    "InvalidTransitionError", "PaymentError", "PaymentStateError",
    "RentalStageError", "TripNotFoundError", "UnknownBranchError",
    "VehicleNotReadyError",
    "DamageAssessment", "DamageInspector", "LowChargeRule", "ReturnRule",
    "TRANSITIONS", "InMemoryStatuses", "StatusRepository", "VehicleLifecycle",
    "Branch", "Damage", "DamageKind", "ElectricVehicle", "InspectionReport",
    "LoyaltyTier", "PriceLine", "Quote", "Transition", "Trip", "TripStage",
    "VehicleState", "VehicleStatus",
    "InMemoryPaymentGateway", "PaymentGateway", "PaymentRecord",
    "PaymentService", "Settlement",
    "FleetUtilisation", "InMemoryLoyalty", "LongRentalDiscount",
    "LoyaltyDirectory", "LoyaltyDiscount", "PricingContext", "PricingRule",
    "RuleChainPricing", "SurgeRule", "UtilisationSource", "WeekendRule",
    "build_desk",
]
