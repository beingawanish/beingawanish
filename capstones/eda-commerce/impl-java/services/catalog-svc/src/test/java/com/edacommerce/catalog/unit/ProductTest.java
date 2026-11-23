package com.edacommerce.catalog.unit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.edacommerce.catalog.domain.Availability;
import com.edacommerce.catalog.domain.CatalogException;
import com.edacommerce.catalog.domain.Product;
import com.edacommerce.catalog.domain.ProductStatus;
import com.edacommerce.kernel.Money;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ProductTest {
  static Product p(long list, Long sale) {
    return new Product(
        "SKU-1",
        "Shoe",
        null,
        null,
        List.of("Sport"),
        Map.of(),
        ProductStatus.ACTIVE,
        100,
        List.of(),
        Money.of(list, "EUR"),
        sale == null ? null : Money.of(sale, "EUR"),
        0,
        0);
  }

  @Test
  void upsertBumpsVersionsAndDetectsPriceChanges() {
    Product.Upsert first = Product.upsert(null, p(100, null));
    assertThat(first.product().version()).isEqualTo(1);
    assertThat(first.priceChanged()).isTrue();
    Product.Upsert same = Product.upsert(first.product(), p(100, null));
    assertThat(same.priceChanged()).isFalse();
    assertThat(same.product().version()).isEqualTo(2);
    assertThat(same.product().priceVersion()).isEqualTo(1);
    Product.Upsert sale = Product.upsert(same.product(), p(100, 80L));
    assertThat(sale.priceChanged()).isTrue();
    assertThat(sale.product().priceVersion()).isEqualTo(2);
  }

  @Test
  void rejectsInvalidProducts() {
    assertThatThrownBy(() -> p(-1, null)).isInstanceOf(CatalogException.class);
    assertThatThrownBy(
            () ->
                new Product(
                    "SKU",
                    "x",
                    null,
                    null,
                    null,
                    null,
                    ProductStatus.ACTIVE,
                    null,
                    null,
                    Money.of(1, "EUR"),
                    Money.of(1, "USD"),
                    0,
                    0))
        .isInstanceOf(CatalogException.class);
  }

  @Test
  void availabilityIsAdvisory() {
    assertThat(Availability.of(null)).isEqualTo(Availability.UNKNOWN);
    assertThat(Availability.of(0)).isEqualTo(Availability.OUT_OF_STOCK);
    assertThat(Availability.of(5)).isEqualTo(Availability.LOW_STOCK);
    assertThat(Availability.of(6)).isEqualTo(Availability.IN_STOCK);
  }
}
