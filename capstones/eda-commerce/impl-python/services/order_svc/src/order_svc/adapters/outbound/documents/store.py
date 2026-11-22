"""DocumentStore port on top of edacommon's ClaimCheckStore (S3 / MinIO)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from edacommon.claimcheck import ClaimCheck, ClaimCheckStore


class ClaimCheckDocuments:
    def __init__(self, store: ClaimCheckStore) -> None:
        self._store = store

    def put(self, bucket: str, key: str, data: bytes, content_type: str) -> dict[str, Any]:
        # Invoices are kept under legal retention: expiresAt null (ClaimCheck doc).
        return self._store.put(bucket, key, data, content_type).to_avro()

    def presign(self, claim_check: dict[str, Any], ttl_s: int) -> str:
        return self._store.presign(ClaimCheck.from_avro(claim_check), timedelta(seconds=ttl_s))
