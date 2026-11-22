package com.edacommerce.shipping.application;

import com.edacommerce.shipping.domain.TrackingUpdate;
import java.util.List;

/** Port: the stored raw carrier webhooks (tracking_event), applied after the response. */
public interface TrackingEvents {

  /** A stored webhook that has not been applied yet. */
  record Stored(String carrierEventId, String rawStatus, TrackingUpdate update) {}

  /** Up to {@code limit} unapplied webhooks in carrier-timestamp order, locked (SKIP LOCKED). */
  List<Stored> lockUnprocessed(int limit);

  void markProcessed(String carrierEventId, String outcome);
}
