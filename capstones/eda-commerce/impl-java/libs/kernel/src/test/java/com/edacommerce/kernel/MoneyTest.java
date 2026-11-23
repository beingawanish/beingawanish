package com.edacommerce.kernel;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.math.BigDecimal;
import net.jqwik.api.ForAll;
import net.jqwik.api.Property;
import net.jqwik.api.constraints.LongRange;
import org.junit.jupiter.api.Test;

class MoneyTest {
  @Test
  void addsAndMultipliesInMinorUnits() {
    assertThat(Money.of(1999, "EUR").times(3).plus(Money.of(499, "EUR")))
        .isEqualTo(Money.of(6496, "EUR"));
  }

  @Test
  void refusesToMixCurrencies() {
    assertThatThrownBy(() -> Money.of(1, "EUR").plus(Money.of(1, "USD")))
        .isInstanceOf(Money.CurrencyMismatchException.class);
    assertThatThrownBy(() -> Money.of(1, "eur")).isInstanceOf(IllegalArgumentException.class);
  }

  @Test
  void includedTaxUsesBankersRounding() {
    BigDecimal vat = new BigDecimal("0.19");
    // 12999 * 0.19 / 1.19 = 2075.48... -> 2075
    assertThat(Money.of(12999, "EUR").includedTax(vat)).isEqualTo(Money.of(2075, "EUR"));
    // exactly .5 cases round to even: 119 * 0.19/1.19 = 19.0; 1309*0.19/1.19 = 209.0; use rate 1
    // (50 %)
    assertThat(Money.of(1, "EUR").includedTax(BigDecimal.ONE)).isEqualTo(Money.of(0, "EUR"));
    assertThat(Money.of(3, "EUR").includedTax(BigDecimal.ONE)).isEqualTo(Money.of(2, "EUR"));
    assertThat(Money.of(5, "EUR").includedTax(BigDecimal.ONE)).isEqualTo(Money.of(2, "EUR"));
  }

  @Property
  void additionIsCommutativeAndMinusInvertsPlus(
      @ForAll @LongRange(min = -1_000_000_000L, max = 1_000_000_000L) long a,
      @ForAll @LongRange(min = -1_000_000_000L, max = 1_000_000_000L) long b) {
    Money x = Money.of(a, "EUR");
    Money y = Money.of(b, "EUR");
    assertThat(x.plus(y)).isEqualTo(y.plus(x));
    assertThat(x.plus(y).minus(y)).isEqualTo(x);
  }
}
