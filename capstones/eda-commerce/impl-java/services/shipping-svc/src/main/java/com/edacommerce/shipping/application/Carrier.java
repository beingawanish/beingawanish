package com.edacommerce.shipping.application;

import com.edacommerce.shipping.domain.Direction;
import com.edacommerce.shipping.domain.PostalAddress;

/**
 * Port to the carrier (anti-corruption layer): the domain never sees carrier status strings or API
 * errors. The fake carrier implements it; a real adapter replaces it. Booking must be idempotent on
 * shipmentId (a rollback and retry returns the same tracking number).
 */
public interface Carrier {

  /** A confirmed booking. */
  record Booking(String carrier, String trackingNumber) {}

  /** The carrier API is unavailable or refused the booking for now; try again later. */
  class UnavailableException extends RuntimeException {
    private static final long serialVersionUID = 1L;

    public UnavailableException(String message) {
      super(message);
    }
  }

  Booking book(String shipmentId, Direction direction, PostalAddress address, int parcelCount);
}
