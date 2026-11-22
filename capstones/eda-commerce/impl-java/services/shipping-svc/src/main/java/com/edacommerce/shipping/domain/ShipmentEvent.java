package com.edacommerce.shipping.domain;

import java.time.Instant;

/**
 * Facts on shipping.events.v1. Each carries the shipment's aggregate version after the change; one
 * transition emitting n events advances the version by n.
 */
public sealed interface ShipmentEvent {
  long version();

  record Created(long version) implements ShipmentEvent {}

  record InTransit(long version, String carrierEventId, String location, Instant carrierTimestamp)
      implements ShipmentEvent {}

  record Delivered(long version, String carrierEventId, Instant deliveredAt)
      implements ShipmentEvent {}

  /**
   * @param code ADDRESS_ISSUE, DAMAGED, LOST, DELAYED, BOOKING_FAILED or UNKNOWN
   */
  record Problem(
      long version, String code, String detail, String carrierEventId, Instant raisedAt)
      implements ShipmentEvent {}
}
