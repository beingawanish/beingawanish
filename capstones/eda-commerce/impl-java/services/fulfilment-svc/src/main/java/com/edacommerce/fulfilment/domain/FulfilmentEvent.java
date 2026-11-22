package com.edacommerce.fulfilment.domain;

/**
 * Facts on fulfilment.events.v1 about an outbound order. Each carries the fulfilment's aggregate
 * version after the change; one transition emitting n events advances the version by n.
 */
public sealed interface FulfilmentEvent {
  long version();

  record Accepted(long version) implements FulfilmentEvent {}

  record Picked(long version) implements FulfilmentEvent {}

  record Packed(long version) implements FulfilmentEvent {}

  record Dispatched(long version) implements FulfilmentEvent {}

  record Cancelled(long version) implements FulfilmentEvent {}

  record Failed(long version) implements FulfilmentEvent {}
}
