package com.edacommerce.inventory.application;

import com.edacommerce.inventory.domain.Restock;
import java.util.Optional;

/** Port: restocks, keyed by the returns saga's restockId. */
public interface RestockRepository {
  Optional<Restock> find(String restockId);

  void save(Restock restock);
}
