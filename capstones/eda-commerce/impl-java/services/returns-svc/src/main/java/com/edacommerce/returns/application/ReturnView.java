package com.edacommerce.returns.application;

import com.edacommerce.returns.domain.LabelRef;
import java.time.Instant;
import java.util.List;

/** returns.yaml Return, plus the label reference behind GET /returns/{id}/label. */
public record ReturnView(
    String returnId,
    String orderId,
    String rmaNumber,
    String status,
    List<Line> lines,
    Long refundAmountMinor,
    String currency,
    LabelRef label,
    Instant parcelDueBy,
    Instant requestedAt,
    String reason,
    String comment) {

  /** One returned line (one per inspection outcome once inspected). */
  public record Line(String lineId, String sku, int quantity, String inspectionOutcome) {}

  public boolean labelAvailable() {
    return label != null;
  }
}
