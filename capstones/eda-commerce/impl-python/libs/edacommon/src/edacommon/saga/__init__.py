"""Saga kit (guide §4.2, ADR-0008): repository with optimistic locking, transition log, the engine
that applies one transition per transaction, the deadline sweeper and the ops endpoints.

Each orchestrator provides only its pure transition function (domain) and the mapping of its
decisions to messages (application). Everything else is here.
"""

from edacommon.saga.engine import PendingMessage, SagaEngine, SagaStep
from edacommon.saga.repository import ConcurrentSagaUpdate, SagaRepository, SagaRow
from edacommon.saga.sweeper import DeadlineSweeper

__all__ = [
    "ConcurrentSagaUpdate",
    "DeadlineSweeper",
    "PendingMessage",
    "SagaEngine",
    "SagaRepository",
    "SagaRow",
    "SagaStep",
]
