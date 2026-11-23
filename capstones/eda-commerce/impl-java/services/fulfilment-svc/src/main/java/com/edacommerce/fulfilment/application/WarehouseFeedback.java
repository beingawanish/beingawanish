package com.edacommerce.fulfilment.application;

import com.edacommerce.fulfilment.domain.FailureReason;
import com.edacommerce.fulfilment.domain.InspectionOutcome;
import com.edacommerce.fulfilment.domain.Parcel;
import java.time.Instant;
import java.util.List;
import java.util.Map;

/**
 * Inbound port: what the warehouse reports back. Each call is one unit of work; a call that throws
 * is repeated by the warehouse adapter (a real WMS retries its callbacks the same way).
 */
public interface WarehouseFeedback {
  void accepted(String fulfilmentId, String warehouseId, Instant estimatedDispatchAt);

  void picked(String fulfilmentId);

  /**
   * @param manifest the packing manifest (per-item scans, lots, serials); large on purpose
   */
  void packed(String fulfilmentId, List<Parcel> parcels, byte[] manifest);

  void failed(String fulfilmentId, FailureReason reason, String detail);

  /** Per-unit outcomes by lineId. */
  void inspected(String returnId, Map<String, List<InspectionOutcome>> unitOutcomes);
}
