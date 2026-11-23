"""LabelStore port on top of edacommon's ClaimCheckStore (S3 / MinIO)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from edacommon.claimcheck import ClaimCheckStore


class ClaimCheckLabels:
    def __init__(self, store: ClaimCheckStore) -> None:
        self._store = store

    def put(self, bucket: str, key: str, data: bytes, content_type: str, expires_at: datetime) -> dict[str, Any]:
        return self._store.put(bucket, key, data, content_type, expires_at=expires_at).to_avro()
