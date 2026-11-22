package com.edacommerce.catalog.application;

import com.edacommerce.catalog.domain.Product;
import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.transaction.annotation.Transactional;

/** Catalog use cases: upsert (with outbox snapshots), browse, stock projection. */
public class CatalogUseCases {
  private final ProductRepository products;
  private final OutboxWriter outbox;
  private final Clock clock;
  private final IdGenerator ids;

  public CatalogUseCases(
      ProductRepository products, OutboxWriter outbox, Clock clock, IdGenerator ids) {
    this.products = products;
    this.outbox = outbox;
    this.clock = clock;
    this.ids = ids;
  }

  @Transactional
  public Product upsert(Product incoming) {
    Product.Upsert u =
        Product.upsert(products.findForUpdate(incoming.sku()).orElse(null), incoming);
    products.save(u.product());
    // An admin write starts its own flow; the correlation id groups the two snapshots it publishes.
    Causation cause = Causation.root(ids.newId());
    outbox.append(CatalogMessages.productUpserted(u.product()), cause);
    if (u.priceChanged()) {
      outbox.append(CatalogMessages.priceChanged(u.product(), clock.instant()), cause);
    }
    return u.product();
  }

  public Optional<Product> find(String sku) {
    return products.find(sku);
  }

  public List<Product> browse(String category, String query, String afterSku, int limit) {
    return products.browse(category, query, afterSku, limit);
  }

  public Integer available(String sku) {
    return products.available(sku);
  }

  @Transactional
  public boolean stockLevel(
      String sku, int onHand, int reserved, int available, long version, Instant asOf) {
    return products.applyStockLevel(sku, onHand, reserved, available, version, asOf);
  }
}
