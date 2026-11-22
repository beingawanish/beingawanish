package com.edacommerce.returns.application;

import java.util.List;
import java.util.Map;
import java.util.Optional;

/** Port: the query side of returns (return_request, return_line), written with each transition. */
public interface ReturnRepository {
  void save(ReturnView view, String customerId, String sagaState, boolean holdsQuantity);

  Optional<ReturnView> find(String returnId);

  /** The customer a return belongs to. */
  Optional<String> owner(String returnId);

  List<ReturnView> forOrder(String orderId);

  /** Quantity per lineId held by the order's returns that still hold it. */
  Map<String, Integer> heldQuantities(String orderId);

  boolean anyForOrder(String orderId);

  /** Allocates the next RMA sequence of {@code year} (row lock: gapless). */
  long nextRmaSequence(int year);
}
