"""Consumer runtime (guide §4.1, ADR-0006, ADR-0007).

* :mod:`.registry`   - handlers registered by ``ce_type`` with their reader schema
* :mod:`.processor`  - the per-record algorithm of guide §4.1, broker-independent and unit-tested
* :mod:`.forwarder`  - retry-topic / DLQ forwarding with the ``x-*`` headers
* :mod:`.loop`       - the confluent-kafka poll loop (main and retry consumers), offsets, shutdown
* :mod:`.dlq`        - DLQ peek and replay for ``/ops/dlq``
"""

from edacommon.consumer.processor import MessageProcessor, Outcome
from edacommon.consumer.record import ConsumedRecord
from edacommon.consumer.registry import HandlerRegistry

__all__ = ["ConsumedRecord", "HandlerRegistry", "MessageProcessor", "Outcome"]
