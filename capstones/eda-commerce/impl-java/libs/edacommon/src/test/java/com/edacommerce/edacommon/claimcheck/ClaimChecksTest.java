package com.edacommerce.edacommon.claimcheck;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.edacommerce.common.ClaimCheck;
import com.edacommerce.edacommon.errors.NonRetryableException;
import com.edacommerce.edacommon.errors.RetryLaterException;
import com.edacommerce.edacommon.testing.InMemoryClaimCheckStore;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import org.junit.jupiter.api.Test;

class ClaimChecksTest {
  @Test
  void keysAreDeterministicFromBusinessIds() {
    assertThat(ClaimChecks.key("order", Instant.parse("2026-11-18T09:46:40Z"), "o1", "i1", "pdf"))
        .isEqualTo("order/2026/11/o1/i1.pdf");
  }

  @Test
  void getVerifiesHashAndSizeAndMissingObjectsRetryLater() {
    InMemoryClaimCheckStore store = new InMemoryClaimCheckStore();
    byte[] bytes = "invoice".getBytes(StandardCharsets.UTF_8);
    ClaimCheck cc =
        store.put("invoices", "order/2026/11/o1/i1.pdf", bytes, "application/pdf", null);
    assertThat(cc.getSha256()).isEqualTo(ClaimChecks.sha256(bytes)).hasSize(64);
    assertThat(cc.getSizeBytes()).isEqualTo(bytes.length);
    assertThat(store.get(cc)).isEqualTo(bytes);

    store.corrupt("invoices", "order/2026/11/o1/i1.pdf");
    assertThatThrownBy(() -> store.get(cc)).isInstanceOf(NonRetryableException.class);
    ClaimCheck missing = ClaimCheck.newBuilder(cc).setObjectKey("nope").build();
    assertThatThrownBy(() -> store.get(missing)).isInstanceOf(RetryLaterException.class);
  }
}
