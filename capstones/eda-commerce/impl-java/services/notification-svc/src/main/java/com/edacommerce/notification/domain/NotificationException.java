package com.edacommerce.notification.domain;

/** A rule of the notification domain was violated (mapped to NonRetryable). */
public class NotificationException extends RuntimeException {
  private static final long serialVersionUID = 1L;

  public NotificationException(String message) {
    super(message);
  }
}
