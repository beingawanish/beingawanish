"""Claim check against an S3 API (moto) and webhook signature rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws

from edacommon.claimcheck import ClaimCheck, ClaimCheckStore, object_key
from edacommon.errors import NonRetryable, RetryLater
from edacommon.testing import metrics_for_test
from edacommon.testing.fakes import collect
from edacommon.webhooks import sign, verify


@pytest.fixture
def store():  # type: ignore[no-untyped-def]
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="invoices")
        metrics, reader = metrics_for_test()
        yield ClaimCheckStore(s3, metrics), reader


def test_put_get_verify_and_metric(store) -> None:  # type: ignore[no-untyped-def]
    s, reader = store
    at = datetime(2026, 11, 18, tzinfo=UTC)
    key = object_key("order", at, "o-1", "inv-1", "pdf")
    assert key == "order/2026/11/o-1/inv-1.pdf"
    cc = s.put("invoices", key, b"%PDF-1.7 hello", "application/pdf")
    assert cc.size_bytes == 14 and len(cc.sha256) == 64
    assert ClaimCheck.from_avro(cc.to_avro()) == cc
    assert s.get(cc) == b"%PDF-1.7 hello"
    assert "Signature" in s.presign(cc, timedelta(minutes=5))
    data = collect(reader)
    assert {p.attributes["direction"] for p in data["eda.claimcheck.object.size"]} == {"put", "get"}


def test_missing_object_is_retry_later(store) -> None:  # type: ignore[no-untyped-def]
    s, _ = store
    with pytest.raises(RetryLater):
        s.get(ClaimCheck(bucket="invoices", object_key="nope", content_type="application/pdf", size_bytes=1, sha256="0" * 64))


def test_hash_mismatch_is_non_retryable(store) -> None:  # type: ignore[no-untyped-def]
    s, _ = store
    cc = s.put("invoices", "k", b"abc", "text/plain")
    with pytest.raises(NonRetryable):
        s.get(ClaimCheck(bucket=cc.bucket, object_key=cc.object_key, content_type=cc.content_type,
                         size_bytes=cc.size_bytes, sha256="f" * 64))


def test_same_key_overwrites_on_retry(store) -> None:  # type: ignore[no-untyped-def]
    s, _ = store
    s.put("invoices", "order/2026/11/o/i.pdf", b"one", "application/pdf")
    cc = s.put("invoices", "order/2026/11/o/i.pdf", b"two", "application/pdf")
    assert s.get(cc) == b"two"


def test_webhook_signature_and_tolerance() -> None:
    now = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
    ts = int(now.timestamp())
    body = b'{"pspEventId":"e9"}'
    sig = sign("dev-psp-secret", ts, body)
    assert verify("dev-psp-secret", str(ts), body, sig, now)
    assert not verify("dev-psp-secret", str(ts), body + b" ", sig, now)          # tampered body
    assert not verify("other", str(ts), body, sig, now)                          # wrong secret
    assert not verify("dev-psp-secret", str(ts - 301), body, sign("dev-psp-secret", ts - 301, body), now)  # stale
    assert verify("dev-psp-secret", str(ts - 299), body, sign("dev-psp-secret", ts - 299, body), now)
    assert not verify("dev-psp-secret", None, body, sig, now)
