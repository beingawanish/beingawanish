"""``GET /ops/sagas/{sagaId}`` and ``POST /ops/sagas/{sagaId}/retry-step`` (admin.yaml SagaView)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request, Response

from edacommon.db import Database, UnitOfWork
from edacommon.errors import DomainError
from edacommon.idempotency import HEADER, IdempotencyStore, StoredResponse
from edacommon.ids import rfc3339
from edacommon.saga.repository import SagaRepository, SagaRow


class SagaNotFound(DomainError):
    problem_type = "not-found"
    status = 404


class SagaNotRetryable(DomainError):
    problem_type = "saga-not-retryable"
    status = 409


def saga_view(db: Database, saga_id: str) -> dict[str, Any]:
    with db.unit_of_work() as uow:
        repo = SagaRepository(uow.session)
        row = repo.get(saga_id)
        if row is None:
            raise SagaNotFound(f"no saga {saga_id}")
        history = repo.history(saga_id)
    return {
        "sagaId": row.saga_id,
        "sagaType": row.saga_type,
        "state": row.state,
        "version": row.version,
        "deadlineAt": rfc3339(row.deadline_at) if row.deadline_at else None,
        "attempts": row.step_attempts,
        "history": [
            {
                "at": rfc3339(h.at),
                "from": h.from_state,
                "to": h.to_state,
                "trigger": h.trigger_type,
                "eventId": h.trigger_id or "",
            }
            for h in history
        ],
    }


def saga_ops_router(
    *,
    db: Database,
    idempotency: IdempotencyStore,
    retry_step: Callable[[UnitOfWork, SagaRow], bool],
    caller_of: Callable[[Request], str],
) -> APIRouter:
    """``retry_step(uow, locked_row)`` re-issues the current step's command; ``False`` -> 409."""
    router = APIRouter(tags=["ops"])

    @router.get("/ops/sagas/{saga_id}")
    def get_saga(saga_id: str) -> dict[str, Any]:
        return saga_view(db, saga_id)

    @router.post("/ops/sagas/{saga_id}/retry-step", status_code=202)
    async def retry(saga_id: str, request: Request) -> Response:
        body = await request.body()
        caller = caller_of(request)

        def action(uow: UnitOfWork) -> StoredResponse:
            row = SagaRepository(uow.session).load_for_update(saga_id)
            if row is None:
                raise SagaNotFound(f"no saga {saga_id}")
            if not retry_step(uow, row):
                raise SagaNotRetryable(f"saga {saga_id} in state {row.state} has no step to retry")
            return StoredResponse(
                status=202, body=json.dumps({"sagaId": saga_id}).encode(), headers={"content-type": "application/json"}
            )

        from starlette.concurrency import run_in_threadpool

        stored = await run_in_threadpool(
            idempotency.execute,
            db,
            caller=caller,
            key=request.headers.get(HEADER),
            method="POST",
            path=request.url.path,
            body=body,
            action=action,
        )
        return to_response(stored)

    return router


def to_response(stored: StoredResponse) -> Response:
    headers = dict(stored.headers)
    if stored.replayed:
        headers["Idempotent-Replayed"] = "true"
    media = headers.pop("content-type", "application/json")
    return Response(content=stored.body, status_code=stored.status, headers=headers, media_type=media)
