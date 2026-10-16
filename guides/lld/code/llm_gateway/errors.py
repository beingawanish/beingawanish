"""Gateway errors. Two families matter most: ProviderError (something upstream
went wrong; `retryable` says whether trying again can help) and QuotaError
(the calling team hit its own limit; no provider was called)."""


class GatewayError(Exception):
    """Base for every error the gateway raises."""


class InvalidGatewayRequestError(GatewayError):
    pass


class UnknownTeamError(GatewayError):
    pass


class RouteNotFoundError(GatewayError):
    pass


class NoEligibleModelError(GatewayError):
    """The route exists, but every model in it is above the team's cost tier."""


class GuardrailViolationError(GatewayError):
    def __init__(self, guardrail: str, reason: str) -> None:
        super().__init__(f"{guardrail}: {reason}")
        self.guardrail = guardrail


class QuotaError(GatewayError):
    pass


class RateLimitExceededError(QuotaError):
    def __init__(self, team: str, limit: str, retry_after_s: float) -> None:
        super().__init__(f"team {team!r} hit its {limit} limit; retry in {retry_after_s:.1f}s")
        self.team = team
        self.retry_after_s = retry_after_s


class BudgetExhaustedError(QuotaError):
    pass


class CircuitOpenError(GatewayError):
    """Not a ProviderError on purpose: the retrier must never retry it."""


class ProviderError(GatewayError):
    retryable: bool = False
    status: int | None = None

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class ProviderRateLimitError(ProviderError):
    retryable = True
    status = 429


class ProviderOverloadedError(ProviderError):
    retryable = True
    status = 529


class ProviderServerError(ProviderError):
    retryable = True
    status = 500


class ProviderTimeoutError(ProviderError):
    retryable = True


class ProviderInvalidRequestError(ProviderError):
    retryable = False
    status = 400


class AllProvidersFailedError(GatewayError):
    def __init__(self, alias: str, failures: list[tuple[str, Exception]]) -> None:
        detail = "; ".join(f"{key}: {type(err).__name__}" for key, err in failures)
        super().__init__(f"route {alias!r} exhausted: {detail}")
        self.failures = failures
