"""FastAPI app factory: problem details, health, auth, request logging, ops routers (guide §4 ``http``).

* Errors are RFC 9457 problem details; ``type`` URIs live under ``https://errors.edacommerce.example/``.
  Domain errors map to their 4xx, validation errors to 400 with ``errors[]``, dependency outages to
  503 with ``Retry-After`` (guide §6.3: never 500 for a known condition).
* ``/health/live`` = process up. ``/health/ready`` = DB reachable, schema cache warm, consumer
  subscribed. Readiness never depends on another service.
* Auth: ``AUTH_MODE=oidc`` validates bearer JWTs (signature via JWKS, issuer, audience, expiry) and
  authorises on scopes. ``AUTH_MODE=none`` (local only) trusts ``X-Debug-Subject`` or a fixed subject.
* JSON over HTTP is camelCase (guide §5 rule 13): API models extend :class:`CamelModel`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from starlette.concurrency import run_in_threadpool

from edacommon.config import ServiceSettings
from edacommon.errors import DomainError, NonRetryable, RetryLater, Transient, classify
from edacommon.logging import get_logger
from edacommon.tracing import current_ids

log = get_logger(__name__)
PROBLEM_BASE = "https://errors.edacommerce.example/"
PROBLEM_JSON = "application/problem+json"
LOCAL_SUBJECT = "00000000-0000-7000-8000-000000000001"


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


def problem(status: int, problem_type: str, title: str, detail: str | None = None, *,
            errors: list[dict[str, str]] | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
    body: dict[str, Any] = {"type": PROBLEM_BASE + problem_type, "title": title, "status": status}
    if detail:
        body["detail"] = detail
    trace_id, _ = current_ids()
    if trace_id:
        body["traceId"] = trace_id
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


_TITLES = {400: "Bad request", 401: "Unauthorized", 403: "Forbidden", 404: "Not found", 409: "Conflict",
           412: "Precondition failed", 422: "Unprocessable request", 429: "Too many requests",
           503: "Service unavailable"}


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        headers = {"Retry-After": "1"} if exc.status == 409 else None
        return problem(exc.status, exc.problem_type, _TITLES.get(exc.status, "Request refused"), exc.detail,
                       headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"field": ".".join(str(p) for p in e.get("loc", ()) if p != "body"), "message": e.get("msg", "")}
                  for e in exc.errors()]
        return problem(400, "validation-error", "Bad request", "The request failed validation", errors=errors)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        ptype = {401: "unauthorized", 403: "forbidden", 404: "not-found", 405: "method-not-allowed"}.get(
            exc.status_code, "http-error")
        return problem(exc.status_code, ptype, _TITLES.get(exc.status_code, "Error"), str(exc.detail),
                       headers=dict(exc.headers or {}))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        cls = classify(exc)
        if cls in (Transient, RetryLater) and not isinstance(exc, NonRetryable):
            log.warning("dependency unavailable", error=exc)
            return problem(503, "dependency-unavailable", "Service unavailable",
                           "A dependency is temporarily unavailable; retry shortly", headers={"Retry-After": "2"})
        log.error("unhandled error", exc_info=exc)
        return problem(500, "internal-error", "Internal error")


# ------------------------------------------------------------------------------------------ auth
@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    scopes: frozenset[str] = field(default_factory=frozenset)

    def has(self, scope: str) -> bool:
        return scope in self.scopes


class Authenticator:
    def __init__(self, settings: ServiceSettings, *, jwks_client: Any = None) -> None:
        self._mode = settings.auth_mode
        self._issuer = settings.oidc_issuer_url.rstrip("/")
        self._audience = settings.oidc_audience
        self._jwks = jwks_client

    def _jwks_client(self) -> Any:
        if self._jwks is None:
            import jwt

            self._jwks = jwt.PyJWKClient(f"{self._issuer}/protocol/openid-connect/certs", cache_keys=True,
                                         lifespan=300, timeout=5)
        return self._jwks

    def authenticate(self, request: Request) -> Principal:
        if self._mode == "none":
            subject = request.headers.get("X-Debug-Subject") or LOCAL_SUBJECT
            return Principal(subject, frozenset({"shop", "ops"}))
        auth = request.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
        token = auth.split(" ", 1)[1].strip()
        import jwt

        try:
            key = self._jwks_client().get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256", "ES256"], audience=self._audience,
                                issuer=self._issuer, options={"require": ["exp", "iat", "sub"]})
        except jwt.PyJWTError as exc:
            raise HTTPException(401, f"invalid token: {type(exc).__name__}",
                                headers={"WWW-Authenticate": "Bearer"}) from exc
        scopes = frozenset(str(claims.get("scope", "")).split())
        return Principal(str(claims["sub"]), scopes)


def require_scope(auth: Authenticator, scope: str) -> Callable[[Request], Principal]:
    def dep(request: Request) -> Principal:
        principal = auth.authenticate(request)
        if not principal.has(scope):
            raise HTTPException(403, f"scope {scope!r} required")
        request.state.principal = principal
        return principal

    return dep


# ---------------------------------------------------------------------------------------- health
@dataclass
class Readiness:
    checks: dict[str, Callable[[], bool]] = field(default_factory=dict)

    def add(self, name: str, check: Callable[[], bool]) -> None:
        self.checks[name] = check

    def evaluate(self) -> tuple[bool, dict[str, bool]]:
        results: dict[str, bool] = {}
        for name, fn in self.checks.items():
            try:
                results[name] = bool(fn())
            except Exception:
                results[name] = False
        return all(results.values()), results


def health_router(readiness: Readiness) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "UP"}

    @router.get("/health/ready")
    def ready(response: Response) -> dict[str, Any]:
        ok, results = readiness.evaluate()
        response.status_code = 200 if ok else 503
        return {"status": "UP" if ok else "DOWN", "checks": results}

    return router


# ------------------------------------------------------------------------------------------- dlq
def dlq_router(*, dlq: Any, idempotency: Any, db: Any, auth: Authenticator) -> APIRouter:
    """``GET /ops/dlq`` and ``POST /ops/dlq/replay`` (admin.yaml) backed by :class:`DlqOps`."""
    from edacommon.idempotency import HEADER, StoredResponse
    from edacommon.saga.ops import to_response

    router = APIRouter(tags=["ops"])
    ops = Depends(require_scope(auth, "ops"))

    @router.get("/ops/dlq")
    def list_dlq(limit: int = 50, principal: Principal = ops) -> list[dict[str, Any]]:
        from dataclasses import asdict

        return [asdict(e) for e in dlq.peek(min(max(limit, 1), 500))]

    @router.post("/ops/dlq/replay", status_code=202)
    async def replay(request: Request, principal: Principal = ops) -> Response:
        body = await request.body()
        req = json.loads(body) if body else {}

        def action(_: Any) -> StoredResponse:
            n = dlq.replay(max_messages=int(req.get("maxMessages", 100)), event_type=req.get("eventType"),
                           event_ids=req.get("eventIds"))
            return StoredResponse(202, json.dumps({"replayed": n}).encode(), {"content-type": "application/json"})

        stored = await run_in_threadpool(idempotency.execute, db, caller=principal.subject,
                                         key=request.headers.get(HEADER), method="POST", path=request.url.path,
                                         body=body, action=action)
        return to_response(stored)

    return router


# ------------------------------------------------------------------------------------------- app
def create_app(settings: ServiceSettings, *, readiness: Readiness, routers: Sequence[APIRouter] = (),
               title: str | None = None, instrument: bool = True) -> FastAPI:
    app = FastAPI(title=title or settings.service_name, version="1.0.0", docs_url="/docs",
                  openapi_url="/openapi.json", redoc_url=None)
    install_problem_handlers(app)
    app.include_router(health_router(readiness))
    for r in routers:
        app.include_router(r)

    @app.middleware("http")
    async def request_log(request: Request, call_next: Callable[[Request], Any]) -> Any:
        started = time.perf_counter()
        response = await call_next(request)
        if not request.url.path.startswith("/health"):
            route = request.scope.get("route")
            log.info("http request", method=request.method, route=getattr(route, "path", request.url.path),
                     status=response.status_code, duration_ms=round((time.perf_counter() - started) * 1000, 1))
        return response

    if instrument:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app, excluded_urls="/health/live,/health/ready")
        except Exception as exc:  # pragma: no cover - instrumentation is best effort
            log.warning("FastAPI instrumentation unavailable", error=exc)
    return app
