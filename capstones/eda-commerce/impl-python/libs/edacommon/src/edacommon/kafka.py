"""confluent-kafka client configuration (guide §7.1, §5 rules 1-2).

Two traps live here and nowhere else:

* ``partitioner=murmur2_random`` on every producer. librdkafka defaults to CRC32
  (``consistent_random``); Java and Kafka Connect use murmur2. Without this a Python forwarder would
  put an orderId into a different partition from the one Debezium chose (guide §5 rule 1).
* keys are plain UTF-8 bytes, never Avro (rule 2).
"""

from __future__ import annotations

from typing import Any

from edacommon.config import ServiceSettings


def _security(settings: ServiceSettings) -> dict[str, Any]:
    conf: dict[str, Any] = {"security.protocol": settings.kafka_security_protocol}
    if settings.kafka_security_protocol == "SSL":
        conf.update({
            "ssl.ca.location": settings.kafka_ssl_ca_location,
            "ssl.certificate.location": settings.kafka_ssl_cert_location,
            "ssl.key.location": settings.kafka_ssl_key_location,
        })
    return {k: v for k, v in conf.items() if v is not None}


def consumer_config(settings: ServiceSettings, group_id: str, *, client_suffix: str = "") -> dict[str, Any]:
    conf: dict[str, Any] = {
        "bootstrap.servers": settings.kafka_bootstrap_servers,
        "group.id": group_id,
        "client.id": f"{settings.service_name}{client_suffix}",
        "enable.auto.commit": False,               # commit after the DB transaction (§4.1)
        "enable.auto.offset.store": False,
        "auto.offset.reset": "earliest",           # new groups and rebuilt projections see everything
        "isolation.level": "read_committed",
        "partition.assignment.strategy": "cooperative-sticky",
        "session.timeout.ms": 45000,
        "max.poll.interval.ms": 300000,
        "enable.partition.eof": False,
        **_security(settings),
    }
    if settings.kafka_group_instance_id:
        conf["group.instance.id"] = f"{settings.kafka_group_instance_id}{client_suffix}"
    return conf


def producer_config(settings: ServiceSettings, *, client_suffix: str = "-producer") -> dict[str, Any]:
    return {
        "bootstrap.servers": settings.kafka_bootstrap_servers,
        "client.id": f"{settings.service_name}{client_suffix}",
        "acks": "all",
        "enable.idempotence": True,
        "compression.type": "zstd",
        "partitioner": "murmur2_random",           # guide §5 rule 1: same partition as Java/Connect
        "linger.ms": 5,
        **_security(settings),
    }


def encode_key(key: str) -> bytes:
    return key.encode("utf-8")


def murmur2(data: bytes) -> int:
    """Kafka's murmur2 (org.apache.kafka.common.utils.Utils.murmur2), as a signed 32-bit int."""
    seed = 0x9747B28C
    m = 0x5BD1E995
    r = 24
    length = len(data)
    h = (seed ^ length) & 0xFFFFFFFF
    for i in range(0, length - length % 4, 4):
        k = int.from_bytes(data[i:i + 4], "little")
        k = (k * m) & 0xFFFFFFFF
        k ^= k >> r
        k = (k * m) & 0xFFFFFFFF
        h = (h * m) & 0xFFFFFFFF
        h ^= k
    rem = length % 4
    tail = length - rem
    if rem == 3:
        h ^= data[tail + 2] << 16
    if rem >= 2:
        h ^= data[tail + 1] << 8
    if rem >= 1:
        h ^= data[tail]
        h = (h * m) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * m) & 0xFFFFFFFF
    h ^= h >> 15
    return h - (1 << 32) if h & 0x80000000 else h


def java_partition(key: str, partitions: int) -> int:
    """The partition Java's default partitioner (and Kafka Connect) picks for a keyed record."""
    return (murmur2(key.encode("utf-8")) & 0x7FFFFFFF) % partitions
