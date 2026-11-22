package com.edacommerce.returns.domain;

/**
 * Facts on returns.events.v1, each with the return's aggregate version after the change (one
 * transition emitting n events advances it by n).
 */
public sealed interface ReturnEvent {
  long version();

  record Requested(long version) implements ReturnEvent {}

  record Authorized(long version) implements ReturnEvent {}

  record Rejected(long version, String reason) implements ReturnEvent {}

  record Refunded(long version) implements ReturnEvent {}

  record Closed(long version, ReturnOutcome outcome) implements ReturnEvent {}
}
