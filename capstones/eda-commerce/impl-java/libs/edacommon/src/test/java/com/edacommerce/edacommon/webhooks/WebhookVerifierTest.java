package com.edacommerce.edacommon.webhooks;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import org.junit.jupiter.api.Test;

class WebhookVerifierTest {
  static final byte[] BODY = "{\"pspEventId\":\"e9\"}".getBytes(StandardCharsets.UTF_8);
  // hmac.new(b"dev-psp-secret", b"1795000000." + body, sha256).hexdigest()
  static final String SIGNATURE =
      "4bca1a62189c145bcfec6bde3759e8b9e189b55dc13fd44d94847892e8673f58";

  WebhookVerifier at(long epochSeconds) {
    return new WebhookVerifier(
        "dev-psp-secret", Clock.fixed(Instant.ofEpochSecond(epochSeconds), ZoneOffset.UTC));
  }

  @Test
  void acceptsAValidSignatureWithinTolerance() {
    assertThat(at(1795000000L).sign(1795000000L, BODY)).isEqualTo(SIGNATURE);
    assertThat(at(1795000299L).rejectionReason("1795000000", SIGNATURE, BODY)).isNull();
    assertThat(
            at(1795000000L)
                .rejectionReason("1795000000", SIGNATURE.toUpperCase(java.util.Locale.ROOT), BODY))
        .isNull();
  }

  @Test
  void rejectsBadSignaturesStaleTimestampsAndMissingHeaders() {
    assertThat(at(1795000000L).rejectionReason("1795000000", "00" + SIGNATURE.substring(2), BODY))
        .isEqualTo("bad signature");
    assertThat(at(1795000301L).rejectionReason("1795000000", SIGNATURE, BODY))
        .isEqualTo("timestamp outside tolerance");
    assertThat(at(1795000000L).rejectionReason(null, SIGNATURE, BODY)).isNotNull();
    assertThat(at(1795000000L).rejectionReason("abc", SIGNATURE, BODY))
        .isEqualTo("unparseable timestamp");
  }
}
