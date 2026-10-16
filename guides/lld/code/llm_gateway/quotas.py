"""Per-team rate limits (requests/min, tokens/min) and token budgets.

The true token count is unknown until the model answers, so the gateway
reserves an estimate up front (prompt tokens + max_tokens, the worst case),
then settles to the real usage afterwards, or releases the tokens if every
provider failed. One lock guards every team's window and budget, which keeps
the check-then-reserve step atomic.
"""
import threading
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

from .clock import Clock
from .config import TeamPolicy
from .errors import BudgetExhaustedError, RateLimitExceededError, UnknownTeamError


@dataclass
class _WindowEntry:
    at: float
    tokens: int


@dataclass(frozen=True)
class QuotaReservation:
    team: str
    tokens: int
    entry: _WindowEntry


class _TeamState:
    def __init__(self) -> None:
        self.window: deque[_WindowEntry] = deque()
        self.budget_used = 0


class QuotaManager:
    def __init__(self, policies: Mapping[str, TeamPolicy], clock: Clock,
                 window_s: float) -> None:
        self._policies = dict(policies)
        self._clock = clock
        self._window_s = window_s
        self._lock = threading.Lock()
        self._state = {team: _TeamState() for team in self._policies}

    def policy(self, team: str) -> TeamPolicy:
        try:
            return self._policies[team]
        except KeyError:
            raise UnknownTeamError(f"unknown team {team!r}") from None

    def reserve(self, team: str, tokens: int) -> QuotaReservation:
        policy = self.policy(team)
        now = self._clock.now()
        with self._lock:
            state = self._state[team]
            self._prune(state, now)
            if len(state.window) >= policy.requests_per_minute:
                raise RateLimitExceededError(team, "requests/min", self._wait(state, now))
            in_window = sum(entry.tokens for entry in state.window)
            if in_window + tokens > policy.tokens_per_minute:
                raise RateLimitExceededError(team, "tokens/min", self._wait(state, now))
            if state.budget_used + tokens > policy.token_budget:
                raise BudgetExhaustedError(
                    f"team {team!r} would exceed its budget of {policy.token_budget} tokens")
            entry = _WindowEntry(now, tokens)
            state.window.append(entry)
            state.budget_used += tokens
            return QuotaReservation(team, tokens, entry)

    def settle(self, reservation: QuotaReservation, actual_tokens: int) -> None:
        """Swap the estimate for the real count, in the window and the budget."""
        with self._lock:
            state = self._state[reservation.team]
            state.budget_used += actual_tokens - reservation.tokens
            reservation.entry.tokens = actual_tokens

    def release(self, reservation: QuotaReservation) -> None:
        """Nothing was generated: refund the tokens, keep the request counted."""
        self.settle(reservation, 0)

    def budget_remaining(self, team: str) -> int:
        policy = self.policy(team)
        with self._lock:
            return policy.token_budget - self._state[team].budget_used

    def _prune(self, state: _TeamState, now: float) -> None:
        while state.window and now - state.window[0].at >= self._window_s:
            state.window.popleft()

    def _wait(self, state: _TeamState, now: float) -> float:
        return state.window[0].at + self._window_s - now if state.window else 0.0
