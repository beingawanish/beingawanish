"""Claim check for large payloads and documents (ADR-0009, architecture §7).

Order of operations is the whole point: **object first, event second**. ``put`` uploads before the
producer writes its outbox row; a rollback leaves an orphan object for the lifecycle rule, never an
event that points at nothing. Keys are deterministic from business ids, so a retry overwrites the
same object. ``get`` verifies size and SHA-256; a missing object is :class:`RetryLater` (it may not be
visible yet), an unreachable store is :class:`Transient`, a hash mismatch is :class:`NonRetryable`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from edacommon.errors import NonRetryable, RetryLater, Transient
from edacommon.ids import to_millis
from edacommon.metrics import EdaMetrics


def object_key(context: str, at: datetime, aggregate_id: str, document_id: str, ext: str) -> str:
    """``<context>/<yyyy>/<mm>/<aggregateId>/<documentId>.<ext>`` (ADR-0009)."""
    return f"{context}/{at:%Y}/{at:%m}/{aggregate_id}/{document_id}.{ext.lstrip('.')}"


@dataclass(frozen=True, slots=True)
class ClaimCheck:
    bucket: str
    object_key: str
    content_type: str
    size_bytes: int
    sha256: str
    expires_at: datetime | None = None
    store: str = "s3"

    def to_avro(self) -> dict[str, Any]:
        return {"store": self.store, "bucket": self.bucket, "objectKey": self.object_key,
                "contentType": self.content_type, "sizeBytes": self.size_bytes, "sha256": self.sha256,
                "expiresAt": self.expires_at}

    @classmethod
    def from_avro(cls, d: dict[str, Any]) -> ClaimCheck:
        exp = d.get("expiresAt")
        if isinstance(exp, int):
            from edacommon.ids import from_millis

            exp = from_millis(exp)
        return cls(bucket=d["bucket"], object_key=d["objectKey"], content_type=d["contentType"],
                   size_bytes=int(d["sizeBytes"]), sha256=d["sha256"], expires_at=exp, store=d.get("store", "s3"))

    def expires_at_millis(self) -> int | None:
        return to_millis(self.expires_at) if self.expires_at else None


class ClaimCheckStore:
    def __init__(self, s3_client: Any, metrics: EdaMetrics) -> None:
        self._s3 = s3_client
        self._metrics = metrics

    @classmethod
    def from_settings(cls, *, endpoint: str, region: str, access_key: str, secret_key: str,
                      metrics: EdaMetrics) -> ClaimCheckStore:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3", endpoint_url=endpoint, region_name=region, aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(s3={"addressing_style": "path"}, signature_version="s3v4", connect_timeout=3, read_timeout=10,
                          retries={"max_attempts": 2, "mode": "standard"}),
        )
        return cls(client, metrics)

    def put(self, bucket: str, key: str, data: bytes, content_type: str, *,
            expires_at: datetime | None = None) -> ClaimCheck:
        digest = hashlib.sha256(data).hexdigest()
        try:
            self._s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type,
                                Metadata={"sha256": digest})
        except Exception as exc:
            raise _classify(exc, f"put s3://{bucket}/{key}") from exc
        self._metrics.claimcheck_size(bucket=bucket, direction="put", size=len(data))
        return ClaimCheck(bucket=bucket, object_key=key, content_type=content_type, size_bytes=len(data),
                          sha256=digest, expires_at=expires_at)

    def get(self, cc: ClaimCheck) -> bytes:
        try:
            obj = self._s3.get_object(Bucket=cc.bucket, Key=cc.object_key)
            data: bytes = obj["Body"].read()
        except Exception as exc:
            raise _classify(exc, f"get s3://{cc.bucket}/{cc.object_key}") from exc
        if len(data) != cc.size_bytes or hashlib.sha256(data).hexdigest() != cc.sha256:
            raise NonRetryable(f"claim check s3://{cc.bucket}/{cc.object_key} failed size/sha256 verification")
        self._metrics.claimcheck_size(bucket=cc.bucket, direction="get", size=len(data))
        return data

    def presign(self, cc: ClaimCheck, ttl: timedelta = timedelta(minutes=5)) -> str:
        url: str = self._s3.generate_presigned_url(
            "get_object", Params={"Bucket": cc.bucket, "Key": cc.object_key}, ExpiresIn=int(ttl.total_seconds()))
        return url


def _classify(exc: Exception, what: str) -> Exception:
    code = ""
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        code = str(resp.get("Error", {}).get("Code", ""))
        status = resp.get("ResponseMetadata", {}).get("HTTPStatusCode")
    else:
        status = None
    if code in ("NoSuchKey", "404", "NotFound", "NoSuchBucket"):
        return RetryLater(f"{what}: object not found (yet)")
    if status is not None and int(status) >= 500 or type(exc).__name__ in (
        "EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError", "ConnectionClosedError"):
        return Transient(f"{what}: object store unavailable: {exc}")
    return RetryLater(f"{what}: {exc}")
