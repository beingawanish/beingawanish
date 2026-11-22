package com.edacommerce.checkout.contract;

import com.edacommerce.catalog.PriceChanged;
import com.edacommerce.catalog.ProductUpserted;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.inventory.StockLevelChanged;
import com.edacommerce.order.OrderCancelled;
import com.edacommerce.order.OrderPlaced;
import org.junit.jupiter.api.Test;

/**
 * Consumed golden messages decode; the produced CheckoutSubmitted is validated in
 * CheckoutServiceIT.
 */
class CheckoutContractTest {
  @Test
  void consumedMessagesDecodeFromTheirGoldenBytes() {
    GoldenFixtures.assertSpecificRoundTrip(ProductUpserted.class);
    GoldenFixtures.assertSpecificRoundTrip(PriceChanged.class);
    GoldenFixtures.assertSpecificRoundTrip(StockLevelChanged.class);
    GoldenFixtures.assertSpecificRoundTrip(OrderPlaced.class);
    GoldenFixtures.assertSpecificRoundTrip(OrderCancelled.class);
  }
}
