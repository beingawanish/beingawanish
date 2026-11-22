package com.edacommerce.notification.application;

import java.util.List;

/**
 * Port to the email/SMS gateway (anti-corruption layer). The fake implements it today. The
 * idempotency key is derived from the triggering fact, so a send repeated after a rollback is
 * recognised by the gateway and not delivered twice.
 */
public interface MailGateway {

  /** A file to attach. */
  @SuppressWarnings("ArrayRecordComponent")
  record Attachment(String filename, String contentType, byte[] content) {}

  /** One message. {@code to} is personal data. */
  record Email(
      String idempotencyKey, String to, String subject, String body, List<Attachment> attachments) {
    @Override
    public String toString() {
      return "Email[" + idempotencyKey + ", redacted]";
    }
  }

  void send(Email email);
}
