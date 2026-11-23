package com.edacommerce.shipping.application;

import com.edacommerce.shipping.domain.Shipment;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

/** Port: shipments. */
public interface ShipmentRepository {
  Optional<Shipment> findForUpdate(String shipmentId);

  Optional<Shipment> findByFulfilmentForUpdate(String fulfilmentId);

  Optional<Shipment> findByTrackingNumberForUpdate(String trackingNumber);

  /** Ids of pending bookings that are due, locked with SKIP LOCKED (parallel retriers). */
  List<String> lockDueBookings(Instant now, int limit);

  void save(Shipment shipment);
}
