"""Engine, sessions and the unit of work; the shared tables as SQLAlchemy Core (guide §4).

A :class:`UnitOfWork` is one database transaction. The consumer runtime opens one per record; HTTP
use cases open one per request. Everything that must be atomic with the business change happens on
``uow.session``: inbox insert, outbox rows, saga row and transition row.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Engine,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Session, sessionmaker

from edacommon.config import ServiceSettings

shared_metadata = MetaData()

outbox_table = Table(
    "outbox", shared_metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("aggregate_type", Text, nullable=False),
    Column("aggregate_id", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("topic", Text, nullable=False),
    Column("payload", LargeBinary, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("producer", Text, nullable=False),
    Column("correlation_id", Text, nullable=False),
    Column("causation_id", Text),
    Column("traceparent", Text),
    Column("tracestate", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("published_at", DateTime(timezone=True)),
)

inbox_table = Table(
    "inbox", shared_metadata,
    Column("message_id", Text, primary_key=True),
    Column("consumer", Text, primary_key=True),
    Column("message_type", Text, nullable=False),
    Column("source_topic", Text),
    Column("source_partition", Integer),
    Column("source_offset", BigInteger),
    Column("received_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)

idempotency_table = Table(
    "idempotency_key", shared_metadata,
    Column("caller", Text, primary_key=True),
    Column("key", Text, primary_key=True),
    Column("request_hash", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("response_status", Integer),
    Column("response_headers", JSONB),
    Column("response_body", LargeBinary),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)

saga_instance_table = Table(
    "saga_instance", shared_metadata,
    Column("saga_id", Text, primary_key=True),
    Column("saga_type", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("data", JSONB, nullable=False),
    Column("version", BigInteger, nullable=False, server_default=text("0")),
    Column("deadline_at", DateTime(timezone=True)),
    Column("step_attempts", Integer, nullable=False, server_default=text("0")),
    Column("correlation_id", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("completed_at", DateTime(timezone=True)),
)

saga_transition_table = Table(
    "saga_transition", shared_metadata,
    Column("saga_id", Text, primary_key=True),
    Column("seq", BigInteger, primary_key=True),
    Column("from_state", Text, nullable=False),
    Column("to_state", Text, nullable=False),
    Column("trigger_type", Text, nullable=False),
    Column("trigger_id", Text),
    Column("at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)


def make_engine(settings: ServiceSettings, *, url: str | None = None, **kw: Any) -> Engine:
    return create_engine(
        url or settings.db_url,
        pool_size=settings.db_pool_size,
        max_overflow=0,
        pool_timeout=2,            # guide §6.5: 2 s pool acquisition -> fast 503 when Postgres stalls
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5, "application_name": settings.service_name},
        **kw,
    )


class UnitOfWork:
    """One transaction. Use as a context manager; commits on success, rolls back on exception."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self._after_commit: list[Callable[[], None]] = []

    def after_commit(self, fn: Callable[[], None]) -> None:
        """Run ``fn`` after a successful commit (e.g. wake the relay). Never for side effects
        that must be atomic with the transaction."""
        self._after_commit.append(fn)

    def run_after_commit(self) -> None:
        for fn in self._after_commit:
            fn()
        self._after_commit.clear()


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False, autoflush=True)

    @contextmanager
    def unit_of_work(self) -> Iterator[UnitOfWork]:
        session = self._sessions()
        uow = UnitOfWork(session)
        try:
            with session.begin():
                yield uow
        finally:
            session.close()
        uow.run_after_commit()

    def ping(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def dispose(self) -> None:
        self.engine.dispose()
