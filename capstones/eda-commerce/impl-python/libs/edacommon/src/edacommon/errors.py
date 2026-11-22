"""Error classification (guide §6.3, ADR-0007).

Every adapter maps its own exceptions to one of three classes, once, where they are raised. The
consumer runtime only looks at the class:

* :class:`Transient`    - retry in place with backoff (DB failover, deadlock, 503). Partition paused.
* :class:`RetryLater`   - forward to the next retry topic (dependency degraded, object not there yet).
* :class:`NonRetryable` - straight to the DLQ (cannot deserialise, invariant violated, bad input).

Unknown exceptions count as RetryLater (ADR-0007): they get three non-blocking chances before a human
looks at them, and they never block a partition.
"""

from __future__ import annotations


class EdaError(Exception):
    """Base class of classified errors."""


class Transient(EdaError):
    """Clears in seconds. Retried in place, without committing the offset."""


class RetryLater(EdaError):
    """Clears in minutes. The record moves to <group>.retry.* and the partition moves on."""


class NonRetryable(EdaError):
    """Never clears by waiting. The record goes to <group>.dlq and an alert fires."""


class DomainError(Exception):
    """A business rule refused the operation. HTTP maps it to 4xx, messaging to NonRetryable."""

    problem_type = "domain-error"
    status = 422

    def __init__(self, detail: str, *, problem_type: str | None = None, status: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if problem_type:
            self.problem_type = problem_type
        if status:
            self.status = status


# psycopg / SQLSTATE codes that mean "try the same thing again in a moment".
_TRANSIENT_SQLSTATES = {
    "40001",  # serialization_failure
    "40P01",  # deadlock_detected
    "55P03",  # lock_not_available
    "57P01",  # admin_shutdown (failover)
    "57P02",  # crash_shutdown
    "57P03",  # cannot_connect_now
    "53300",  # too_many_connections
    "08000", "08003", "08006", "08001", "08004",  # connection exceptions
}


def classify(exc: BaseException) -> type[EdaError]:
    """Map an arbitrary exception to its error class. Classified errors map to themselves."""
    if isinstance(exc, EdaError):
        return type(exc) if type(exc) in (Transient, RetryLater, NonRetryable) else _base_of(exc)
    if isinstance(exc, DomainError):
        return NonRetryable
    # SQLAlchemy wraps DBAPI errors; look at the original psycopg error and its SQLSTATE.
    orig = getattr(exc, "orig", None) or exc
    sqlstate = getattr(orig, "sqlstate", None)
    if sqlstate in _TRANSIENT_SQLSTATES:
        return Transient
    try:
        from sqlalchemy import exc as sa_exc

        if isinstance(exc, sa_exc.TimeoutError):  # pool acquisition timeout (2 s, guide §6.5)
            return Transient
        if isinstance(exc, sa_exc.OperationalError) and getattr(exc, "connection_invalidated", False):
            return Transient
        if isinstance(exc, sa_exc.DisconnectionError):
            return Transient
    except ImportError:  # pragma: no cover
        pass
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return Transient
    # ADR-0007: anything unclassified is RetryLater. Deserialisation and validation failures are
    # classified explicitly (serde raises NonRetryable), so a bug in a handler gets three
    # non-blocking retries and then a human, instead of silently blocking or dropping data.
    return RetryLater


def _base_of(exc: EdaError) -> type[EdaError]:
    for base in (Transient, RetryLater, NonRetryable):
        if isinstance(exc, base):
            return base
    return RetryLater
