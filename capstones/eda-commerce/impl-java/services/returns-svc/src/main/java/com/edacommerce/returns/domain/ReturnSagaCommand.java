package com.edacommerce.returns.domain;

import java.time.Instant;
import java.util.Map;

/** Commands the returns saga sends (the application adds addresses and lines when mapping). */
public sealed interface ReturnSagaCommand {
  record IssueReturnLabel(String shipmentId) implements ReturnSagaCommand {}

  record ExpectReturn(Instant expectedBy) implements ReturnSagaCommand {}

  record RestockItems(String restockId, Map<String, Integer> lines) implements ReturnSagaCommand {}

  record RefundPayment(String refundId, long amountMinor) implements ReturnSagaCommand {}
}
