package com.edacommerce.returns.adapters.in.http;

import com.edacommerce.returns.application.ReturnView;
import java.time.Instant;
import java.util.List;

/** returns.yaml Return. */
public record ReturnJson(
    String returnId,
    String orderId,
    String rmaNumber,
    String status,
    List<LineJson> lines,
    MoneyJson refundAmount,
    boolean labelAvailable,
    Instant parcelDueBy,
    Instant requestedAt) {

  /** One returned line. */
  public record LineJson(String lineId, String sku, int quantity, String inspectionOutcome) {}

  /** common.yaml Money. */
  public record MoneyJson(long amountMinor, String currency) {}

  static ReturnJson of(ReturnView v) {
    return new ReturnJson(
        v.returnId(),
        v.orderId(),
        v.rmaNumber(),
        v.status(),
        v.lines().stream()
            .map(l -> new LineJson(l.lineId(), l.sku(), l.quantity(), l.inspectionOutcome()))
            .toList(),
        v.refundAmountMinor() == null ? null : new MoneyJson(v.refundAmountMinor(), v.currency()),
        v.labelAvailable(),
        v.parcelDueBy(),
        v.requestedAt());
  }
}
