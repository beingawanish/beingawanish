package com.edacommerce.inventory.application;

import com.edacommerce.inventory.domain.StockEffect;
import com.edacommerce.inventory.domain.StockLevel;
import java.util.Collection;
import java.util.Map;
import java.util.Optional;

/** Port: stock rows. */
public interface StockRepository {
  /** Locks the rows of {@code skus} in SKU order (so two orders never deadlock); missing SKUs are absent. */
  Map<String, StockLevel> lockAll(Collection<String> skus);

  /**
   * Applies one effect with a conditional update. Throws if the condition fails, which under the row
   * locks above means a bug, never a race.
   */
  void apply(StockEffect effect);

  Optional<StockLevel> find(String sku);

  /** Admin seeding: creates or replaces on-hand stock; refuses to go below what is reserved. */
  StockLevel setOnHand(String sku, int onHand);
}
