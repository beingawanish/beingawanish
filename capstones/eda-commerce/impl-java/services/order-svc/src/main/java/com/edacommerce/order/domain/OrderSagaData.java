package com.edacommerce.order.domain;

import com.edacommerce.kernel.Money;
import java.time.Instant;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.List;
import java.util.Set;

/**
 * Saga-local data (saga_instance.data): business ids minted once per step and reused on every
 * resend (architecture §5.3 rule 2), compensation bookkeeping, facts recorded early (rule 4). A
 * plain mutable holder: the transition function works on a copy and returns it.
 */
public final class OrderSagaData {
  public String orderId;
  public Money total;
  public String reservationId;
  public String paymentId;
  public String fulfilmentId;
  public int fulfilmentAttempt;
  public String invoiceId;
  public String shipmentId;
  public String carrier;
  public String trackingNumber;
  public Instant authorizationExpiresAt;
  public boolean reservationExpired;
  public boolean confirmed;
  public boolean captured;
  public Money capturedAmount;
  public int captureRetries;
  public Set<Compensation> outstanding = EnumSet.noneOf(Compensation.class);
  public int compensationAttempts;
  public CancellationReason cancellationReason;
  public String cancellationDetail;
  public boolean paymentVoided;
  public OrderSagaState attentionFrom;
  public String attentionIssue;
  public long eventVersion;
  public List<OrderSagaTrigger> pending = new ArrayList<>();

  public OrderSagaData copy() {
    OrderSagaData d = new OrderSagaData();
    d.orderId = orderId;
    d.total = total;
    d.reservationId = reservationId;
    d.paymentId = paymentId;
    d.fulfilmentId = fulfilmentId;
    d.fulfilmentAttempt = fulfilmentAttempt;
    d.invoiceId = invoiceId;
    d.shipmentId = shipmentId;
    d.carrier = carrier;
    d.trackingNumber = trackingNumber;
    d.authorizationExpiresAt = authorizationExpiresAt;
    d.reservationExpired = reservationExpired;
    d.confirmed = confirmed;
    d.captured = captured;
    d.capturedAmount = capturedAmount;
    d.captureRetries = captureRetries;
    d.outstanding =
        outstanding.isEmpty() ? EnumSet.noneOf(Compensation.class) : EnumSet.copyOf(outstanding);
    d.compensationAttempts = compensationAttempts;
    d.cancellationReason = cancellationReason;
    d.cancellationDetail = cancellationDetail;
    d.paymentVoided = paymentVoided;
    d.attentionFrom = attentionFrom;
    d.attentionIssue = attentionIssue;
    d.eventVersion = eventVersion;
    d.pending = new ArrayList<>(pending);
    return d;
  }

  long nextVersion() {
    return ++eventVersion;
  }
}
