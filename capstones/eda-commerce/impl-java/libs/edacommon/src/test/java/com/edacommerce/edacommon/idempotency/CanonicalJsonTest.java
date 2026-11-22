package com.edacommerce.edacommon.idempotency;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

/**
 * Cross-language vectors computed with Python's json.dumps(sort_keys=True, separators=(",", ":")).
 */
class CanonicalJsonTest {
  static final String BODY =
      "{ \"expectedTotal\": {\"currency\": \"EUR\", \"amountMinor\": 12999},"
          + " \"cartId\": \"0190f0a4-7a7e-7c43-9a63-4e0d4f0a1b2c\", \"note\": \"Grüße\","
          + " \"lines\": [{\"sku\": \"SKU-1001\", \"qty\": 2}] }";

  @Test
  void sortsKeysRecursivelyAndDropsWhitespace() {
    assertThat(CanonicalJson.canonicalise(BODY.getBytes(StandardCharsets.UTF_8)))
        .isEqualTo(
            "{\"cartId\":\"0190f0a4-7a7e-7c43-9a63-4e0d4f0a1b2c\",\"expectedTotal\":{\"amountMinor\":12999,"
                + "\"currency\":\"EUR\"},\"lines\":[{\"qty\":2,\"sku\":\"SKU-1001\"}],\"note\":\"Grüße\"}");
  }

  @Test
  void requestHashMatchesThePythonBuild() {
    assertThat(
            CanonicalJson.requestHash("POST", "/checkouts", BODY.getBytes(StandardCharsets.UTF_8)))
        .isEqualTo("4a40798bc0ce30771cde68f8c06c3bbc313e9517b6c17f9c623231305b3a6e87");
    assertThat(CanonicalJson.requestHash("POST", "/carts", new byte[0]))
        .isEqualTo("9a6301b6b92578a6af1da057d4da2a90ad056b7539d0462fd3184d63a77e9486");
  }
}
