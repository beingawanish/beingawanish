package com.edacommerce.edacommon.claimcheck;

import com.edacommerce.common.ClaimCheck;
import java.net.URL;
import java.time.Duration;
import java.time.Instant;
import org.springframework.lang.Nullable;

/**
 * Claim-check port (ADR-0009). Producers put the object <em>before</em> their database transaction
 * and put the returned {@link ClaimCheck} in the event; consumers get it back, verified.
 */
public interface ClaimCheckStore {

  /**
   * Uploads {@code bytes} under a deterministic key (a retry overwrites the same object).
   *
   * @param expiresAt when the bucket's lifecycle rule deletes it; null for legal hold (invoices)
   */
  ClaimCheck put(
      String bucket, String key, byte[] bytes, String contentType, @Nullable Instant expiresAt);

  /**
   * Downloads and verifies size and SHA-256.
   *
   * @throws com.edacommerce.edacommon.errors.RetryLaterException if the object is not there (yet)
   * @throws ClaimCheckExpiredException if the claim check's expiresAt has passed
   * @throws com.edacommerce.edacommon.errors.NonRetryableException on a hash or size mismatch
   */
  byte[] get(ClaimCheck claimCheck);

  /** A pre-signed GET URL for humans and emails (5 minutes for invoices). */
  URL presign(ClaimCheck claimCheck, Duration ttl);
}
