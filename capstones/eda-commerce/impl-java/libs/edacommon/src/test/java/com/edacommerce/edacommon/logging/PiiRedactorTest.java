package com.edacommerce.edacommon.logging;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.checkout.CheckoutSubmitted;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import java.util.Map;
import org.junit.jupiter.api.Test;

class PiiRedactorTest {
  @Test
  void fieldsTaggedPiiAreRedacted() {
    CheckoutSubmitted c = GoldenFixtures.decode(CheckoutSubmitted.class);
    Map<String, Object> safe = PiiRedactor.redact(c);
    assertThat(safe.get("contactEmail")).isEqualTo(PiiRedactor.REDACTED);
    assertThat(safe.get("shippingAddress")).isEqualTo(PiiRedactor.REDACTED);
    assertThat(safe.toString())
        .doesNotContain("jane.doe@example.com", "Jane Doe", "Invalidenstrasse");
    assertThat(safe.get("orderId")).isEqualTo(c.getOrderId());
  }
}
