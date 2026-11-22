package com.edacommerce.kernel;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Objects;
import java.util.regex.Pattern;

/**
 * An amount in integer minor units with an ISO 4217 currency (guide §6.2, §5 rule 8). Arithmetic
 * refuses to mix currencies; rounding, where needed, is banker's rounding (HALF_EVEN), defined here
 * once.
 */
public record Money(long amountMinor, String currency) implements Comparable<Money> {
  private static final Pattern CURRENCY = Pattern.compile("[A-Z]{3}");

  public Money {
    Objects.requireNonNull(currency, "currency");
    if (!CURRENCY.matcher(currency).matches()) {
      throw new IllegalArgumentException("currency must be ISO 4217 upper case: " + currency);
    }
  }

  public static Money of(long amountMinor, String currency) {
    return new Money(amountMinor, currency);
  }

  public static Money zero(String currency) {
    return new Money(0, currency);
  }

  public Money plus(Money other) {
    requireSameCurrency(other);
    return new Money(Math.addExact(amountMinor, other.amountMinor), currency);
  }

  public Money minus(Money other) {
    requireSameCurrency(other);
    return new Money(Math.subtractExact(amountMinor, other.amountMinor), currency);
  }

  public Money times(int quantity) {
    return new Money(Math.multiplyExact(amountMinor, (long) quantity), currency);
  }

  /**
   * The tax contained in a tax-inclusive (gross) amount: {@code gross * rate / (1 + rate)}, rounded
   * half-even to the minor unit. Applied per line, then summed.
   */
  public Money includedTax(BigDecimal rate) {
    BigDecimal gross = BigDecimal.valueOf(amountMinor);
    BigDecimal tax = gross.multiply(rate).divide(BigDecimal.ONE.add(rate), 0, RoundingMode.HALF_EVEN);
    return new Money(tax.longValueExact(), currency);
  }

  public boolean isNegative() {
    return amountMinor < 0;
  }

  @Override
  public int compareTo(Money other) {
    requireSameCurrency(other);
    return Long.compare(amountMinor, other.amountMinor);
  }

  private void requireSameCurrency(Money other) {
    if (!currency.equals(other.currency)) {
      throw new CurrencyMismatchException(currency, other.currency);
    }
  }

  /** Adding or comparing different currencies is a bug, never an exchange. */
  public static final class CurrencyMismatchException extends IllegalArgumentException {
    private static final long serialVersionUID = 1L;

    CurrencyMismatchException(String a, String b) {
      super("cannot combine " + a + " and " + b);
    }
  }
}
