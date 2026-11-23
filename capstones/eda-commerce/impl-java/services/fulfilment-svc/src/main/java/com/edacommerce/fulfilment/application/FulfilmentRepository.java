package com.edacommerce.fulfilment.application;

import com.edacommerce.fulfilment.domain.Fulfilment;
import java.util.Optional;

/** Port: outbound warehouse orders, keyed by fulfilmentId. */
public interface FulfilmentRepository {
  /** Loads and row-locks a fulfilment (serialises commands, warehouse feedback and dispatch). */
  Optional<Fulfilment> findForUpdate(String fulfilmentId);

  Optional<Fulfilment> find(String fulfilmentId);

  /** Inserts or updates, parcels included. */
  void save(Fulfilment fulfilment);
}
