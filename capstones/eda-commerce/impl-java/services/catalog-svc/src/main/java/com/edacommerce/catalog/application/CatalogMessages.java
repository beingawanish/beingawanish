package com.edacommerce.catalog.application;

import com.edacommerce.catalog.PriceChanged;
import com.edacommerce.catalog.ProductUpserted;
import com.edacommerce.catalog.domain.Product;
import com.edacommerce.common.Money;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import java.time.Instant;

/**
 * Full snapshots on the compacted topics, keyed by sku (consumers treat each as the whole truth).
 */
public final class CatalogMessages {
  private CatalogMessages() {}

  public static final String PRODUCT_TOPIC = "catalog.product.v1";
  public static final String PRICE_TOPIC = "catalog.price.v1";
  public static final String PRICE_LIST = "retail-eu";

  public static OutgoingMessage productUpserted(Product p) {
    ProductUpserted e =
        ProductUpserted.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setSku(p.sku())
            .setName(p.name())
            .setDescription(p.description())
            .setBrand(p.brand())
            .setCategoryPath(p.categoryPath())
            .setAttributes(p.attributes())
            .setStatus(com.edacommerce.catalog.ProductStatus.valueOf(p.status().name()))
            .setWeightGrams(p.weightGrams())
            .setImageUrls(p.imageUrls())
            .build();
    return OutgoingMessage.of(PRODUCT_TOPIC, p.sku(), e, "Product", p.sku(), p.version());
  }

  public static OutgoingMessage priceChanged(Product p, Instant validFrom) {
    PriceChanged e =
        PriceChanged.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setSku(p.sku())
            .setPriceListId(PRICE_LIST)
            .setListPrice(money(p.listPrice()))
            .setSalePrice(p.salePrice() == null ? null : money(p.salePrice()))
            .setValidFrom(validFrom)
            .setValidUntil(null)
            .build();
    return OutgoingMessage.of(PRICE_TOPIC, p.sku(), e, "Price", p.sku(), p.priceVersion());
  }

  static Money money(com.edacommerce.kernel.Money m) {
    return new Money(m.amountMinor(), m.currency());
  }
}
