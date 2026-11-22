package com.edacommerce.catalog.contract;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.catalog.application.CatalogMessages;
import com.edacommerce.catalog.domain.Product;
import com.edacommerce.catalog.domain.ProductStatus;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.inventory.StockLevelChanged;
import com.edacommerce.kernel.Money;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class CatalogContractTest {
  @Test
  void consumedAndProducedMessagesMatchTheContract() {
    GoldenFixtures.assertSpecificRoundTrip(StockLevelChanged.class);
    Product p =
        new Product(
            "SKU-1",
            "Shoe",
            "d",
            "b",
            List.of("a"),
            Map.of("colour", "red"),
            ProductStatus.ACTIVE,
            1,
            List.of("u"),
            Money.of(100, "EUR"),
            Money.of(80, "EUR"),
            3,
            2);
    var up = CatalogMessages.productUpserted(p);
    assertThat(up.topic()).isEqualTo("catalog.product.v1");
    assertThat(up.key()).isEqualTo("SKU-1");
    assertThat(up.aggregateVersion()).isEqualTo(3);
    GoldenFixtures.assertValidAgainstBundled(up.record());
    var price = CatalogMessages.priceChanged(p, Instant.EPOCH);
    assertThat(price.topic()).isEqualTo("catalog.price.v1");
    assertThat(price.aggregateVersion()).isEqualTo(2);
    GoldenFixtures.assertValidAgainstBundled(price.record());
  }
}
