"""HTTP ``Idempotency-Key`` handling (ADR-0012, guide §4 ``idempotency``, §5 rule 14).

Semantics, identical in both builds:

* hash = SHA-256 over ``METHOD + "\\n" + path + "\\n" + canonical JSON body`` (sorted keys, no
  insignificant whitespace, UTF-8);
* first request: row inserted ``IN_PROGRESS`` **in the same transaction** as the business change and
  completed with the stored response before commit;
* same key + same body, completed: replay the stored response with ``Idempotent-Replayed: true``;
* same key + same body, still running: ``409`` with ``Retry-After``;
* same key + different body: ``422``.

"Still running" is detected with a transaction-scoped advisory lock on ``(caller, key)``: the first
request holds it until its transaction ends, so a concurrent duplicate gets ``409`` immediately
instead of blocking on the primary-key insert and then replaying. Rows live 24 hours.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.orm import Session

from edacommon.db import Database, UnitOfWork, idempotency_table as t
from edacommon.errors import DomainError
from edacommon.ids import Clock

HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
MAX_KEY_LENGTH = 255
TTL = timedelta(hours=24)


def canonical_json(body: bytes | str | None) -> str:
    if body is None or (isinstance(body, (bytes, str)) and len(body) == 0):
        return ""
    obj = json.loads(body)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_hash(method: str, path: str, body: bytes | str | None) -> str:
    payload = f"{method.upper()}\n{path}\n{canonical_json(body)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _lock_key(caller: str, key: str) -> int:
    digest = hashlib.sha256(f"{caller}\x00{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


class IdempotencyConflict(DomainError):
    problem_type = "idempotency-conflict"
    status = 409


class IdempotencyMismatch(DomainError):
    problem_type = "idempotency-key-reused"
    status = 422


class IdempotencyKeyInvalid(DomainError):
    problem_type = "validation-error"
    status = 400


@dataclass(frozen=True, slots=True)
class StoredResponse:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    replayed: bool = False

    def json(self) -> Any:
        return json.loads(self.body) if self.body else None


class BeginResult(StrEnum):
    PROCEED = "proceed"
    REPLAY = "replay"


class IdempotencyStore:
    def __init__(self, clock: Clock, ttl: timedelta = TTL) -> None:
        self._clock = clock
        self._ttl = ttl

    @staticmethod
    def validate_key(key: str | None) -> str:
        if not key:
            raise IdempotencyKeyInvalid("Idempotency-Key header is required for this request")
        if len(key) > MAX_KEY_LENGTH:
            raise IdempotencyKeyInvalid(f"Idempotency-Key is longer than {MAX_KEY_LENGTH} characters")
        return key

    def begin(self, session: Session, *, caller: str, key: str, req_hash: str) -> StoredResponse | None:
        """Return a stored response to replay, or ``None`` to proceed (row now IN_PROGRESS)."""
        locked = session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"),
                                 {"k": _lock_key(caller, key)}).scalar_one()
        if not locked:
            raise IdempotencyConflict("A request with this Idempotency-Key is still being processed")
        now = self._clock.now()
        row = session.execute(select(t).where(t.c.caller == caller, t.c.key == key)).mappings().first()
        if row is not None and row["expires_at"] <= now:
            session.execute(delete(t).where(t.c.caller == caller, t.c.key == key))
            row = None
        if row is not None:
            if row["request_hash"] != req_hash:
                raise IdempotencyMismatch("This Idempotency-Key was already used with a different request body")
            if row["status"] == "IN_PROGRESS":
                # Only reachable if another build or a crashed writer left the row behind.
                raise IdempotencyConflict("A request with this Idempotency-Key is still being processed")
            return StoredResponse(status=int(row["response_status"]), body=bytes(row["response_body"] or b""),
                                  headers=dict(row["response_headers"] or {}), replayed=True)
        session.execute(insert(t).values(caller=caller, key=key, request_hash=req_hash, status="IN_PROGRESS",
                                         created_at=now, expires_at=now + self._ttl))
        return None

    def complete(self, session: Session, *, caller: str, key: str, response: StoredResponse) -> None:
        session.execute(update(t).where(t.c.caller == caller, t.c.key == key).values(
            status="COMPLETED", response_status=response.status, response_headers=response.headers,
            response_body=response.body))

    def execute(self, db: Database, *, caller: str, key: str | None, method: str, path: str,
                body: bytes | None, action: Callable[[UnitOfWork], StoredResponse]) -> StoredResponse:
        """Run ``action`` at most once per (caller, key). Domain errors roll everything back, so a
        retry after a 4xx re-validates instead of replaying the error."""
        k = self.validate_key(key)
        try:
            h = request_hash(method, path, body)
        except json.JSONDecodeError as exc:
            raise IdempotencyKeyInvalid(f"request body is not valid JSON: {exc}") from exc
        with db.unit_of_work() as uow:
            stored = self.begin(uow.session, caller=caller, key=k, req_hash=h)
            if stored is not None:
                return stored
            response = action(uow)
            self.complete(uow.session, caller=caller, key=k, response=response)
        return response
