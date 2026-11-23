package com.edacommerce.shipping.domain;

import java.util.Optional;

/**
 * The carrier's tracking vocabulary (webhooks.yaml CarrierTrackingEvent) with its rank. EXCEPTION
 * has no rank: it is reported whenever seen.
 */
public enum CarrierStatus {
  LABEL_CREATED(0),
  PICKED_UP(1),
  IN_TRANSIT(2),
  OUT_FOR_DELIVERY(3),
  DELIVERED(4),
  EXCEPTION(-1);

  private final int rank;

  CarrierStatus(int rank) {
    this.rank = rank;
  }

  public int rank() {
    return rank;
  }

  /** Unknown carrier words are not an error: they are stored and ignored. */
  public static Optional<CarrierStatus> parse(String raw) {
    for (CarrierStatus s : values()) {
      if (s.name().equals(raw)) {
        return Optional.of(s);
      }
    }
    return Optional.empty();
  }
}
