"""JSON logs with the fields of guide §6.4 and PII redaction (ADR-0013).

Field names: ``ts``, ``level`` (DEBUG/INFO/WARN/ERROR), ``service``, ``impl``, ``msg``, ``trace_id``,
``span_id``, ``correlation_id``, ``event_id``, ``event_type``, ``order_id``, ``return_id``,
``error.class``, ``error.message``, ``error.stack``.

Two lines of defence against PII:

1. :func:`redact` replaces values of keys known to be personal (and every field tagged
   ``"pii": true`` in the schemas) before a record is logged.
2. A final processor drops any top-level key in :data:`PII_KEYS` that slipped through.

Message payloads are never logged; log ids instead.
"""

from __future__ import annotations

import contextvars
import logging
import sys
import traceback
from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import structlog

from edacommon.tracing import current_ids

PII_KEYS = frozenset(
    {
        "email",
        "contactEmail",
        "contact_email",
        "name",
        "recipientName",
        "recipient_name",
        "address",
        "shippingAddress",
        "shipping_address",
        "shipTo",
        "ship_to",
        "pickupFrom",
        "pickup_from",
        "phone",
        "line1",
        "line2",
        "postalCode",
        "postal_code",
        "paymentMethodToken",
        "payment_method_token",
        "token",
        "authorization",
        "jwt",
        "secret",
        "password",
        "signature",
    }
)
REDACTED = "[REDACTED]"

_log_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("eda_log_ctx", default=None)
_LEVELS = {"warning": "WARN", "warn": "WARN", "critical": "ERROR", "exception": "ERROR"}


def redact(value: Any, extra_keys: frozenset[str] = frozenset()) -> Any:
    keys = PII_KEYS | extra_keys
    if isinstance(value, Mapping):
        return {k: (REDACTED if k in keys else redact(v, extra_keys)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, extra_keys) for v in value]
    return value


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Bind fields (correlation_id, event_id, order_id...) to every log line in this context."""
    current = dict(_log_context.get() or {})
    current.update({k: v for k, v in fields.items() if v is not None})
    token = _log_context.set(current)
    try:
        yield
    finally:
        _log_context.reset(token)


def _add_context(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for k, v in (_log_context.get() or {}).items():
        event.setdefault(k, v)
    trace_id, span_id = current_ids()
    if trace_id:
        event.setdefault("trace_id", trace_id)
        event.setdefault("span_id", span_id)
    return event


def _shape(service: str, impl: str) -> Any:
    def processor(_: Any, method: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        out: dict[str, Any] = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": _LEVELS.get(method, method.upper()),
            "service": service,
            "impl": impl,
            "msg": event.pop("event", ""),
        }
        exc = event.pop("exc_info", None)
        err = event.pop("error", None)
        if exc:
            if exc is True:
                exc = sys.exc_info()
            if isinstance(exc, BaseException):
                exc = (type(exc), exc, exc.__traceback__)
            if exc and exc[0] is not None:
                out["error.class"] = exc[0].__name__
                out["error.message"] = str(exc[1])
                out["error.stack"] = "".join(traceback.format_exception(*exc))
        elif isinstance(err, BaseException):
            out["error.class"] = type(err).__name__
            out["error.message"] = str(err)
        for k, v in event.items():
            if k in PII_KEYS:
                continue  # second line of defence
            out[k] = redact(v)
        return out

    return processor


def configure_logging(service: str, *, level: str = "INFO", fmt: str = "json", impl: str = "python", stream: Any = None) -> None:
    """Configure structlog (and route stdlib logging through it) once per process."""
    renderer: Any = structlog.processors.JSONRenderer() if fmt == "json" else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[_add_context, _shape(service, impl), renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping().get(level.upper(), 20)),
        logger_factory=structlog.PrintLoggerFactory(file=stream or sys.stdout),
        cache_logger_on_first_use=False,
    )

    class _Bridge(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            log = structlog.get_logger(record.name)
            method = {logging.DEBUG: log.debug, logging.INFO: log.info, logging.WARNING: log.warning}.get(
                record.levelno, log.error
            )
            kw: dict[str, Any] = {"logger": record.name}
            if record.exc_info:
                kw["exc_info"] = record.exc_info
            method(record.getMessage(), **kw)

    root = logging.getLogger()
    root.handlers = [_Bridge()]
    root.setLevel(level.upper() if level.upper() != "WARN" else "WARNING")
    for noisy in ("uvicorn.access", "kafka", "botocore", "urllib3", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
