package com.edacommerce.checkout.unit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.edacommerce.checkout.domain.Cart;
import com.edacommerce.checkout.domain.CatalogEntry;
import com.edacommerce.checkout.domain.CheckoutException;
import com.edacommerce.checkout.domain.Pricing;
import com.edacommerce.kernel.Money;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;

class CartPricingTest {
  static final Instant T = Instant.parse("2026-11-18T09:00:00Z");
  static final CatalogEntry SHOE =
      new CatalogEntry(
          "SKU-1001", "Shoe", true, Money.of(12999, "EUR"), null, 50, T.minusSeconds(5));
  static final CatalogEntry LAYER =
      new CatalogEntry(
          "SKU-1002",
          "Layer",
          true,
          Money.of(7999, "EUR"),
          Money.of(5999, "EUR"),
          3,
          T.minusSeconds(9));
  static final CatalogEntry OLD =
      new CatalogEntry("SKU-1007", "Old", false, Money.of(19900, "EUR"), null, 3, T);

  @Test
  void pricesFromTheReadModelWithSalePricesLineVatAndShipping() {
    Cart c = Cart.open("c", "u", "EUR").setItem(SHOE, 1).setItem(LAYER, 2);
    Pricing.Priced p = Pricing.price(c, Map.of("SKU-1001", SHOE, "SKU-1002", LAYER), "STANDARD", T);
    assertThat(p.subtotal()).isEqualTo(Money.of(12999 + 2 * 5999, "EUR"));
    assertThat(p.shippingFee()).isEqualTo(Money.zero("EUR")); // free from 50.00
    assertThat(p.tax())
        .isEqualTo(
            Money.of(12999, "EUR")
                .includedTax(Pricing.VAT)
                .plus(Money.of(11998, "EUR").includedTax(Pricing.VAT)));
    assertThat(p.total()).isEqualTo(p.subtotal());
    assertThat(p.pricedAt()).isEqualTo(T.minusSeconds(9));
    assertThat(p.lines().get(1).availability()).isEqualTo("LOW_STOCK");
    assertThat(
            Pricing.price(
                    Cart.open("c", "u", "EUR").setItem(LAYER, 1),
                    Map.of("SKU-1002", LAYER),
                    "EXPRESS",
                    T)
                .shippingFee())
        .isEqualTo(Money.of(999, "EUR"));
    assertThat(
            Pricing.price(
                    Cart.open("c", "u", "EUR").setItem(LAYER, 1),
                    Map.of("SKU-1002", LAYER),
                    "STANDARD",
                    T)
                .total())
        .isEqualTo(Money.of(5999, "EUR")); // 59.99 qualifies for free standard shipping
  }

  @Test
  void cartRules() {
    Cart c = Cart.open("c", "u", "EUR");
    assertThatThrownBy(() -> c.setItem(OLD, 1))
        .isInstanceOf(CheckoutException.class)
        .hasMessageContaining("SKU-1007");
    assertThatThrownBy(() -> c.setItem(null, 1)).isInstanceOf(CheckoutException.class);
    assertThatThrownBy(() -> c.setItem(LAYER, 4))
        .isInstanceOf(CheckoutException.class)
        .hasMessageContaining("only 3");
    assertThatThrownBy(() -> c.setItem(SHOE, 100)).isInstanceOf(CheckoutException.class);
    Cart done = c.setItem(SHOE, 2).checkedOut();
    assertThat(done.version()).isEqualTo(3);
    assertThatThrownBy(() -> done.setItem(SHOE, 1)).isInstanceOf(CheckoutException.class);
  }

  @Test
  void discontinuedItemsAreReportedAsUnsellable() {
    Cart c = new Cart("c", "u", "EUR", Cart.Status.OPEN, Map.of("SKU-1007", 1), 1);
    assertThat(Pricing.price(c, Map.of("SKU-1007", OLD), "STANDARD", T).unsellable())
        .containsExactly("SKU-1007");
  }
}
