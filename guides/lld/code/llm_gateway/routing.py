"""Routing: turn a request into an ordered fallback chain of models.

A route alias ("smart", "fast") names a chain. A task ("summarise") maps to an
alias, so callers can say what they want done instead of which model does it.
The team's cost tier then filters the chain: a STANDARD team asking for
"smart" gets only the STANDARD-or-cheaper models in that chain.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .config import GatewayConfig, ModelSpec, TeamPolicy
from .errors import NoEligibleModelError, RouteNotFoundError
from .models import ChatRequest


@dataclass(frozen=True)
class RouteDecision:
    alias: str
    targets: tuple[ModelSpec, ...]


class RoutingStrategy(ABC):
    @abstractmethod
    def route(self, request: ChatRequest, policy: TeamPolicy) -> RouteDecision:
        ...


class TableRouter(RoutingStrategy):
    def __init__(self, config: GatewayConfig) -> None:
        self._config = config

    def route(self, request: ChatRequest, policy: TeamPolicy) -> RouteDecision:
        alias = self._resolve_alias(request)
        chain = [self._config.models[key] for key in self._config.routes[alias]]
        allowed = tuple(spec for spec in chain if spec.tier <= policy.max_tier)
        if not allowed:
            raise NoEligibleModelError(
                f"route {alias!r} has no model at or below tier {policy.max_tier.name}")
        return RouteDecision(alias, allowed)

    def _resolve_alias(self, request: ChatRequest) -> str:
        if request.task is not None:
            alias = self._config.task_routes.get(request.task)
            if alias is None:
                raise RouteNotFoundError(f"no route for task {request.task!r}")
            return alias
        assert request.model is not None  # ChatRequest guarantees one of the two
        if request.model not in self._config.routes:
            raise RouteNotFoundError(f"no route alias {request.model!r}")
        return request.model
