package com.edacommerce.fulfilment.application;

import com.edacommerce.fulfilment.domain.OrderLine;
import com.edacommerce.fulfilment.domain.ReturnLine;
import java.util.List;

/**
 * Port to the warehouse management system (anti-corruption layer, architecture §2). The fake WMS
 * implements it today; a real WMS adapter replaces it without touching the domain. Calls are
 * fire-and-forget: progress comes back through {@link WarehouseFeedback}, and a request may be lost
 * without an error (the order saga's deadline recovers, architecture §5.8). Implementations must be
 * idempotent on fulfilmentId and returnId.
 */
public interface Warehouse {

  /** A pick order for the warehouse. */
  record PickOrder(String fulfilmentId, String orderId, List<OrderLine> lines) {}

  void submit(PickOrder order);

  void cancel(String fulfilmentId);

  /** Inspect a received return parcel; outcomes arrive through {@link WarehouseFeedback}. */
  void inspect(String returnId, List<ReturnLine> lines);
}
