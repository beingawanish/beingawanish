package com.edacommerce.catalog.application;

import com.edacommerce.catalog.domain.Product;
import java.util.List;
import java.util.Optional;

/** Port: products, prices and the stock-level projection. */
public interface ProductRepository {
  Optional<Product> findForUpdate(String sku);

  Optional<Product> find(String sku);

  void save(Product product);

  /** Active products, keyset-paginated by sku, optionally filtered by category and free text. */
  List<Product> browse(String category, String query, String afterSku, int limit);

  /** Available units per SKU from inventory.stock-level.v1, null when unknown. */
  Integer available(String sku);

  /** Applies a stock snapshot if its version is newer; false when stale. */
  boolean applyStockLevel(
      String sku, int onHand, int reserved, int available, long version, java.time.Instant asOf);
}
