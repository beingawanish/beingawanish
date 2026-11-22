package com.edacommerce.returns.domain;

import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Saga-local data (saga_instance.data). Business ids (rmaNumber, shipmentId, restockId, refundId)
 * are minted once when the saga enters the step and reused on every resend (architecture §5.3 rule
 * 2; the same refundId on every attempt means a "failed" refund that succeeded at the PSP can never
 * refund twice). A plain mutable holder: the transition function works on a copy.
 */
public final class ReturnSagaData {
  public String returnId;
  public String orderId;
  public String customerId;
  public String paymentId;
  public String currency;
  public ReturnReason reason;
  public String comment;
  public List<ReturnItem> items = new ArrayList<>();
  public boolean firstReturn;
  public long shippingFeeMinor;
  public String warehouseId;
  public String rmaNumber;
  public Instant requestedAt;
  public Instant parcelDueBy;
  public String shipmentId;
  public LabelRef label;
  public boolean received;
  public List<InspectedItem> inspected = new ArrayList<>();
  public long refundAmountMinor;
  public boolean partial;
  public Map<String, Integer> restock = new LinkedHashMap<>();
  public String restockId;
  public String refundId;
  public boolean restocked;
  public boolean refunded;
  public int refundFailures;
  public String rejectReason;
  public ReturnOutcome outcome;
  public String decisionNote;
  public long eventVersion;

  public long valueMinor() {
    return items.stream().mapToLong(ReturnItem::valueMinor).sum();
  }

  public ReturnSagaData copy() {
    ReturnSagaData d = new ReturnSagaData();
    d.returnId = returnId;
    d.orderId = orderId;
    d.customerId = customerId;
    d.paymentId = paymentId;
    d.currency = currency;
    d.reason = reason;
    d.comment = comment;
    d.items = new ArrayList<>(items);
    d.firstReturn = firstReturn;
    d.shippingFeeMinor = shippingFeeMinor;
    d.warehouseId = warehouseId;
    d.rmaNumber = rmaNumber;
    d.requestedAt = requestedAt;
    d.parcelDueBy = parcelDueBy;
    d.shipmentId = shipmentId;
    d.label = label;
    d.received = received;
    d.inspected = new ArrayList<>(inspected);
    d.refundAmountMinor = refundAmountMinor;
    d.partial = partial;
    d.restock = new LinkedHashMap<>(restock);
    d.restockId = restockId;
    d.refundId = refundId;
    d.restocked = restocked;
    d.refunded = refunded;
    d.refundFailures = refundFailures;
    d.rejectReason = rejectReason;
    d.outcome = outcome;
    d.decisionNote = decisionNote;
    d.eventVersion = eventVersion;
    return d;
  }

  long nextVersion() {
    return ++eventVersion;
  }
}
