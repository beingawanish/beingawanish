package com.edacommerce.inventory.domain;

import java.time.Instant;
import java.util.List;

/** The reply inventory-svc sends for a reservation command (inventory.events.v1). */
public sealed interface Reply {
  record Reserved(List<StockLine> lines, Instant expiresAt) implements Reply {}

  record Rejected(List<Shortage> shortages) implements Reply {}

  record Committed(Instant committedAt) implements Reply {}

  record Released(String reason, Instant releasedAt) implements Reply {}

  record Expired(Instant expiredAt) implements Reply {}
}
