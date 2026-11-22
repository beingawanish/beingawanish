package com.edacommerce.edacommon.claimcheck;

import com.edacommerce.common.ClaimCheck;
import com.edacommerce.edacommon.errors.NonRetryableException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.util.HexFormat;
import org.springframework.lang.Nullable;

/** Deterministic keys and hashing for claim checks (ADR-0009). */
public final class ClaimChecks {
  private ClaimChecks() {}

  /** {@code <context>/<yyyy>/<mm>/<aggregateId>/<documentId>.<ext>}, e.g. order/2026/11/o1/i1.pdf. */
  public static String key(String context, Instant at, String aggregateId, String documentId, String ext) {
    ZonedDateTime t = at.atZone(ZoneOffset.UTC);
    return String.format(
        "%s/%04d/%02d/%s/%s.%s", context, t.getYear(), t.getMonthValue(), aggregateId, documentId, ext);
  }

  public static String sha256(byte[] bytes) {
    try {
      return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    } catch (NoSuchAlgorithmException e) {
      throw new IllegalStateException(e);
    }
  }

  public static ClaimCheck of(
      String bucket, String key, byte[] bytes, String contentType, @Nullable Instant expiresAt) {
    return ClaimCheck.newBuilder()
        .setStore("s3")
        .setBucket(bucket)
        .setObjectKey(key)
        .setContentType(contentType)
        .setSizeBytes(bytes.length)
        .setSha256(sha256(bytes))
        .setExpiresAt(expiresAt)
        .build();
  }

  /** Verifies a downloaded object against its claim check. */
  public static byte[] verify(ClaimCheck claimCheck, byte[] bytes) {
    if (bytes.length != claimCheck.getSizeBytes()) {
      throw new NonRetryableException(
          "claim check size mismatch for " + claimCheck.getObjectKey() + ": " + bytes.length
              + " != " + claimCheck.getSizeBytes());
    }
    if (!sha256(bytes).equals(claimCheck.getSha256())) {
      throw new NonRetryableException("claim check sha256 mismatch for " + claimCheck.getObjectKey());
    }
    return bytes;
  }
}
