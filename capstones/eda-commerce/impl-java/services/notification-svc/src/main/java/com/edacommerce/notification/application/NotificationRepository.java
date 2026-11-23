package com.edacommerce.notification.application;

import java.time.Instant;

/** Port: the sent-message log. */
public interface NotificationRepository {

  /** One sent message. */
  record Sent(
      String notificationId,
      String dedupeKey,
      String sourceEventId,
      String template,
      String orderId,
      String customerId,
      String channel,
      int attachmentCount,
      Instant sentAt) {}

  boolean exists(String dedupeKey);

  /** Inserts the row; false if a message with the same dedupe key was already recorded. */
  boolean tryRecord(Sent sent);
}
