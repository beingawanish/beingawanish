package com.edacommerce.shipping.unit;

import com.edacommerce.edacommon.testing.HexagonalArchitecture;
import org.junit.jupiter.api.Test;

class ArchitectureTest {
  @Test
  void dependenciesPointInwards() {
    HexagonalArchitecture.check("com.edacommerce.shipping");
  }
}
