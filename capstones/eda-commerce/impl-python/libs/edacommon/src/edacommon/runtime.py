"""Process composition shared by every service (guide §9 concurrency model).

One process = uvicorn (HTTP, sync route handlers in the thread pool) + one consumer thread per
consumer loop + the retry consumer + background workers (polling relay, sweepers, housekeeping).
SIGTERM: stop accepting work, let every consumer finish its in-flight record and commit, stop the
workers, stop uvicorn, exit within the grace period (k8s base: 30 s).

:class:`Infrastructure` builds the shared building blocks from settings once; services' ``main.py``
composition roots take what they need from it.
"""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from edacommon.config import ServiceSettings
from edacommon.consumer.forwarder import Forwarder
from edacommon.consumer.loop import ConsumerLoop
from edacommon.consumer.processor import MessageProcessor
from edacommon.consumer.registry import HandlerRegistry
from edacommon.db import Database, make_engine
from edacommon.ids import Clock, SystemClock
from edacommon.kafka import consumer_config, producer_config
from edacommon.logging import configure_logging, get_logger
from edacommon.metrics import EdaMetrics, setup_metrics
from edacommon.outbox import Housekeeping, OutboxWriter, PollingRelay
from edacommon.serde import AvroSerde, make_registry_client
from edacommon.tracing import setup_tracing

log = get_logger(__name__)
GRACE_S = 25.0


class Background(Protocol):
    def run(self) -> None: ...

    def stop(self) -> None: ...


class PeriodicTask:
    """Run ``fn`` every ``interval`` until stopped; failures are logged and retried next tick."""

    def __init__(self, name: str, fn: Callable[[], Any], interval: timedelta) -> None:
        self.name = name
        self._fn = fn
        self._interval = interval.total_seconds()
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self._fn()
            except Exception as exc:
                log.warning("periodic task failed", task=self.name, error=exc)
            self._stop.wait(self._interval)

    def stop(self) -> None:
        self._stop.set()


@dataclass
class Infrastructure:
    settings: ServiceSettings
    clock: Clock
    metrics: EdaMetrics
    db: Database
    serde: AvroSerde
    outbox: OutboxWriter
    _producer: Any = None
    meter_provider: Any = None

    @classmethod
    def from_settings(cls, settings: ServiceSettings, *, observability: bool = True,
                      schema_registry: Any = None, clock: Clock | None = None) -> Infrastructure:
        if observability:
            configure_logging(settings.service_name, level=settings.log_level, fmt=settings.log_format)
            attrs = settings.resource_attributes()
            setup_tracing(settings.service_name, attrs, endpoint=settings.otel_exporter_otlp_endpoint,
                          protocol=settings.otel_exporter_otlp_protocol, disabled=settings.otel_sdk_disabled)
            provider = setup_metrics(attrs, endpoint=settings.otel_exporter_otlp_endpoint,
                                     disabled=settings.otel_sdk_disabled)
        else:
            provider = None
        clock = clock or SystemClock()
        metrics = EdaMetrics(provider)
        engine = make_engine(settings)
        if observability:
            try:
                from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

                SQLAlchemyInstrumentor().instrument(engine=engine)
            except Exception as exc:  # pragma: no cover
                log.warning("SQLAlchemy instrumentation unavailable", error=exc)
        serde = AvroSerde(schema_registry or make_registry_client(settings.schema_registry_url))
        return cls(settings=settings, clock=clock, metrics=metrics, db=Database(engine), serde=serde,
                   outbox=OutboxWriter(serde, settings.service_name, clock), meter_provider=provider)

    @property
    def producer(self) -> Any:
        if self._producer is None:
            from confluent_kafka import Producer

            self._producer = Producer(producer_config(self.settings))
        return self._producer

    def processor(self, registry: HandlerRegistry) -> MessageProcessor:
        return MessageProcessor(group=self.settings.group, registry=registry, db=self.db, serde=self.serde,
                                forwarder=Forwarder(self.producer, self.settings.group), metrics=self.metrics,
                                clock=self.clock)

    def consumer_loops(self, registry: HandlerRegistry, topics: list[str], *, threads: int = 1) -> list[ConsumerLoop]:
        """Main loop(s) on the service topics plus one retry loop on <group>.retry.*."""
        from contracts_py.topics import retry_topics

        group = self.settings.group
        proc = self.processor(registry)
        loops = [
            ConsumerLoop(consumer_conf=consumer_config(self.settings, group, client_suffix=f"-{i}"),
                         topics=topics, processor=proc, clock=self.clock, name=f"{group}-{i}")
            for i in range(threads)
        ]
        loops.append(ConsumerLoop(consumer_conf=consumer_config(self.settings, f"{group}-retry", client_suffix="-retry"),
                                  topics=list(retry_topics(group)), processor=proc, clock=self.clock,
                                  retry_mode=True, name=f"{group}-retry"))
        return loops

    def relay(self) -> PollingRelay | None:
        if self.settings.outbox_relay != "polling":
            return None
        return PollingRelay(self.db, self.producer, self.metrics, interval=self.settings.outbox_poll_interval)

    def housekeeping(self) -> PeriodicTask:
        hk = Housekeeping(self.db, self.clock)
        return PeriodicTask("housekeeping", hk.run_once, timedelta(hours=1))

    def dlq_ops(self) -> Any:
        from edacommon.consumer.dlq import DlqOps

        return DlqOps(consumer_conf=consumer_config(self.settings, f"{self.settings.group}-dlq-ops", client_suffix="-dlq"),
                      producer=self.producer, group=self.settings.group, clock=self.clock)


@dataclass
class ServiceRuntime:
    """Runs HTTP plus background threads; owns graceful shutdown."""

    settings: ServiceSettings
    app: Any
    loops: list[ConsumerLoop] = field(default_factory=list)
    workers: list[Background] = field(default_factory=list)
    on_shutdown: list[Callable[[], None]] = field(default_factory=list)

    def run(self) -> None:
        import uvicorn

        threads: list[threading.Thread] = []
        for item in [*self.loops, *self.workers]:
            t = threading.Thread(target=item.run, name=getattr(item, "name", type(item).__name__), daemon=True)
            t.start()
            threads.append(t)
        config = uvicorn.Config(self.app, host="0.0.0.0", port=self.settings.http_port,  # noqa: S104
                                log_config=None, access_log=False, timeout_graceful_shutdown=10)
        server = uvicorn.Server(config)

        def shutdown(signum: int, _frame: Any) -> None:
            log.info("shutdown requested", signal=signal.Signals(signum).name)
            for item in [*self.loops, *self.workers]:
                item.stop()
            server.should_exit = True

        server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        server.run()
        for item in [*self.loops, *self.workers]:
            item.stop()
        for t in threads:
            t.join(timeout=GRACE_S)
        for fn in self.on_shutdown:
            try:
                fn()
            except Exception as exc:  # pragma: no cover
                log.warning("shutdown hook failed", error=exc)
        log.info("service stopped")
