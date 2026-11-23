"""edacommon: the shared runtime of every eda-commerce Python service (implementation guide §4).

Module map (guide §4 table):

=================  ===========================================================================
``ids``            UUIDv7 (RFC 9562) and the clock abstraction
``durations``      ``30s`` / ``200ms`` / ``24h`` duration parsing for configuration
``errors``         Transient / RetryLater / NonRetryable and the one place exceptions are classified
``config``         pydantic-settings base class with every environment variable of guide §7
``envelope``       build and read the Avro ``Envelope``; Kafka headers identical to Debezium's
``serde``          Confluent wire-format Avro with Schema Registry, TopicRecordNameStrategy
``db``             engine, sessions, unit of work, the shared tables as SQLAlchemy Core
``outbox``         ``OutboxWriter`` (same transaction) and the polling relay fallback
``inbox``          idempotent-consumer inbox insert
``consumer``       the processing loop of guide §4.1, retry topics, DLQ, ops endpoints
``saga``           saga repository, transition log, deadline sweeper, ops endpoints
``idempotency``    HTTP Idempotency-Key handling (ADR-0012)
``claimcheck``     object storage claim checks with SHA-256 verification (ADR-0009)
``tracing``        W3C trace context through outbox rows and Kafka headers
``webhooks``       HMAC verification, timestamp tolerance, inbox dedupe, store-then-ack
``http``           FastAPI app factory: problem details, health, auth, request logging
``logging``        JSON logs with the fields of guide §6.4 and PII redaction
``metrics``        the instruments of guide §8 with exact names, units and buckets
``kafka``          confluent-kafka client configuration (guide §7.1)
``runtime``        process composition: threads, signals, graceful shutdown
``testing``        fakes and fixtures used by every service's tests
=================  ===========================================================================
"""

__version__ = "0.1.0"
