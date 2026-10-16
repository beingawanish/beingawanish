"""The answer to "may this request pass?", and how it maps onto HTTP.

Every algorithm returns the same Decision, so the HTTP layer never needs to
know which algorithm made it.
"""
import math
from dataclasses import dataclass
from http import HTTPStatus


@dataclass(frozen=True, slots=True)
class Decision:
    """One rate-limit verdict.

    allowed     -- may the request proceed?
    limit       -- the most requests that can pass at once under this rule
    remaining   -- how many more would pass right now
    retry_after -- seconds until this same request would pass (0 when allowed)
    reset_after -- seconds until the key is back to a full quota
    delay       -- leaky bucket only: wait this long before doing the work
    degraded    -- True when the store failed and the limiter failed open
    """

    allowed: bool
    limit: int
    remaining: int
    retry_after: float
    reset_after: float
    delay: float = 0.0
    degraded: bool = False

    @property
    def status_code(self) -> int:
        return int(HTTPStatus.OK if self.allowed else HTTPStatus.TOO_MANY_REQUESTS)

    def headers(self) -> dict[str, str]:
        """RateLimit-* response headers, plus Retry-After on a 429.

        HTTP wants whole seconds, so times round UP: telling a client to come
        back in 0 seconds when the true answer is 0.3 guarantees another 429.
        A degraded decision sends no headers rather than invented numbers.
        """
        if self.degraded:
            return {}
        headers = {
            "RateLimit-Limit": str(self.limit),
            "RateLimit-Remaining": str(self.remaining),
            "RateLimit-Reset": str(_whole_seconds(self.reset_after)),
        }
        if not self.allowed:
            headers["Retry-After"] = str(max(1, _whole_seconds(self.retry_after)))
        return headers


def _whole_seconds(seconds: float) -> int:
    # Round to milliseconds first so float dust (2.0000000001) doesn't add a second.
    return math.ceil(round(seconds, 3))
