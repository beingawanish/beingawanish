package com.edacommerce.notification.application;

import com.edacommerce.notification.domain.Contact;
import java.time.Instant;
import java.util.Optional;

/** Port: contact details per order (personal data, ADR-0013). */
public interface ContactRepository {
  /** Stores the contact unless one is already known for the order. */
  void saveIfAbsent(Contact contact, Instant now);

  Optional<Contact> find(String orderId);

  /** Deletes contacts past their retention; returns how many. */
  int deleteExpired(Instant now);
}
