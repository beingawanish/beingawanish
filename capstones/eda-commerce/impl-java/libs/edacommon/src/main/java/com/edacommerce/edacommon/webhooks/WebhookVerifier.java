package com.edacommerce.edacommon.webhooks;

import java.nio.charset.StandardCharsets;
import java.security.InvalidKeyException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Locale;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.lang.Nullable;

/**
 * Webhook authentication (webhooks.yaml, ADR-0013): {@code hex(HMAC-SHA256(secret, "<timestamp>.<raw
 * body>"))}, 300 s timestamp tolerance, constant-time comparison.
 */
public class WebhookVerifier {
  public static final Duration TOLERANCE = Duration.ofMinutes(5); // 300 s

  private final byte[] secret;
  private final Clock clock;

  public WebhookVerifier(String secret, Clock clock) {
    this.secret = secret.getBytes(StandardCharsets.UTF_8);
    this.clock = clock;
  }

  /** Why a webhook was rejected; null when it is authentic. */
  @Nullable
  public String rejectionReason(@Nullable String timestampHeader, @Nullable String signature, byte[] body) {
    if (timestampHeader == null || signature == null) {
      return "missing signature or timestamp";
    }
    long ts;
    try {
      ts = Long.parseLong(timestampHeader.trim());
    } catch (NumberFormatException e) {
      return "unparseable timestamp";
    }
    Duration skew = Duration.between(Instant.ofEpochSecond(ts), clock.instant()).abs();
    if (skew.compareTo(TOLERANCE) > 0) {
      return "timestamp outside tolerance";
    }
    byte[] expected = sign(ts, body).getBytes(StandardCharsets.US_ASCII);
    byte[] given = signature.trim().toLowerCase(Locale.ROOT).getBytes(StandardCharsets.US_ASCII);
    return MessageDigest.isEqual(expected, given) ? null : "bad signature";
  }

  public String sign(long timestampSeconds, byte[] body) {
    try {
      Mac mac = Mac.getInstance("HmacSHA256");
      mac.init(new SecretKeySpec(secret, "HmacSHA256"));
      mac.update((timestampSeconds + ".").getBytes(StandardCharsets.UTF_8));
      return HexFormat.of().formatHex(mac.doFinal(body));
    } catch (NoSuchAlgorithmException | InvalidKeyException e) {
      throw new IllegalStateException(e);
    }
  }
}
