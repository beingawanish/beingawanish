package com.edacommerce.returns.domain;

import java.util.List;

/** Everything that can move the returns saga. Replies carry the business id they answer. */
public sealed interface ReturnSagaTrigger {
  /** The saga continues out of a transient state (AUTHORIZED, REJECTED, EXPIRED) or REQUESTED. */
  record Continue() implements ReturnSagaTrigger {}

  /** POST /ops/returns/{id}/decision. */
  record Decision(Kind kind, String note) implements ReturnSagaTrigger {
    /** returns.yaml decision values. */
    public enum Kind {
      APPROVE,
      REJECT,
      RETRY_REFUND,
      CLOSE_WITHOUT_REFUND
    }
  }

  record LabelIssued(String shipmentId, LabelRef label) implements ReturnSagaTrigger {}

  record ParcelReceived() implements ReturnSagaTrigger {}

  record Inspected(List<InspectedItem> results) implements ReturnSagaTrigger {}

  record ItemsRestocked(String restockId) implements ReturnSagaTrigger {}

  record RefundSucceeded(String refundId) implements ReturnSagaTrigger {}

  record RefundFailed(String refundId, boolean retryable, String reason)
      implements ReturnSagaTrigger {}

  record Deadline() implements ReturnSagaTrigger {}

  record OperatorRetry() implements ReturnSagaTrigger {}
}
