"""AttachmentStore port on top of edacommon's ClaimCheckStore: download + size/SHA-256 verification."""

from __future__ import annotations

from typing import Any

from edacommon.claimcheck import ClaimCheck, ClaimCheckStore


class ClaimCheckAttachments:
    def __init__(self, store: ClaimCheckStore) -> None:
        self._store = store

    def get(self, claim_check: dict[str, Any]) -> bytes:
        return self._store.get(ClaimCheck.from_avro(claim_check))
