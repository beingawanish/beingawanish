"""LabelLinks port: 5-minute pre-signed URLs for the return label (ADR-0009: never stream documents)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from edacommon.claimcheck import ClaimCheck, ClaimCheckStore


class ClaimCheckLabelLinks:
    def __init__(self, store: ClaimCheckStore) -> None:
        self._store = store

    def presign(self, claim_check: dict[str, Any], ttl_s: int) -> str:
        return self._store.presign(ClaimCheck.from_avro(claim_check), timedelta(seconds=ttl_s))
