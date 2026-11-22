package com.edacommerce.inventory.application;

import com.edacommerce.inventory.domain.Reservation;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

/** Port: reservations, loaded with a row lock so concurrent commands for one id serialise. */
public interface ReservationRepository {
  Optional<Reservation> findForUpdate(String reservationId);

  void save(Reservation reservation);

  /** Ids of HELD reservations past their TTL, locked with SKIP LOCKED (several sweepers may run). */
  List<String> lockExpired(Instant now, int limit);
}
