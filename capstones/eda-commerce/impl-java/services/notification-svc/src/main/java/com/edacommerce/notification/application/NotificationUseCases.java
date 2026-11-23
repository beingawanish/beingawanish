package com.edacommerce.notification.application;

import com.edacommerce.common.ClaimCheck;
import com.edacommerce.edacommon.claimcheck.ClaimCheckExpiredException;
import com.edacommerce.edacommon.claimcheck.ClaimCheckStore;
import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.errors.RetryLaterException;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.notification.domain.Contact;
import com.edacommerce.notification.domain.NotificationPolicy;
import com.edacommerce.notification.domain.Trigger;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.lang.Nullable;
import org.springframework.transaction.annotation.Transactional;

/**
 * Choreographed reactions (ADR-0001): every use case runs in the consumer's transaction, so the
 * contact, the sent-message row, NotificationSent and the inbox row commit together. Duplicates are
 * stopped twice: by the inbox (same eventId) and by the dedupe key (same fact, new eventId).
 */
public class NotificationUseCases {
  private static final Logger log = LoggerFactory.getLogger(NotificationUseCases.class);
  public static final String CHANNEL = "EMAIL";

  private final ContactRepository contacts;
  private final NotificationRepository notifications;
  private final MailGateway mail;
  private final ClaimCheckStore documents;
  private final OutboxWriter outbox;
  private final IdGenerator ids;
  private final Clock clock;
  private final Duration contactRetention;

  public NotificationUseCases(
      ContactRepository contacts,
      NotificationRepository notifications,
      MailGateway mail,
      ClaimCheckStore documents,
      OutboxWriter outbox,
      IdGenerator ids,
      Clock clock,
      Duration contactRetention) {
    this.contacts = contacts;
    this.notifications = notifications;
    this.mail = mail;
    this.documents = documents;
    this.outbox = outbox;
    this.ids = ids;
    this.clock = clock;
    this.contactRetention = contactRetention;
  }

  /** OrderPlaced: remember how to reach the customer (notification-svc owns contact details). */
  @Transactional
  public void rememberContact(
      String orderId, String customerId, String email, String name, Instant placedAt) {
    contacts.saveIfAbsent(
        Contact.fromOrder(orderId, customerId, email, name, placedAt, contactRetention),
        clock.instant());
  }

  /**
   * Reacts to one fact: decide, fetch the attachment (verified), record, send, publish.
   *
   * @param attachment the fact's document (invoice, label), fetched and SHA-256 verified
   * @return true if a message was sent
   */
  @Transactional
  public boolean notify(
      Trigger trigger,
      String sourceEventId,
      @Nullable ClaimCheck attachment,
      @Nullable String attachmentName,
      Causation causation) {
    Contact contact =
        contacts
            .find(trigger.orderId())
            .orElseThrow(
                () ->
                    // OrderPlaced is on another topic or still in a retry topic: wait for it.
                    new RetryLaterException("no contact yet for order " + trigger.orderId()));
    Optional<NotificationPolicy.Plan> plan = NotificationPolicy.react(trigger, contact.name());
    if (plan.isEmpty() || notifications.exists(plan.get().dedupeKey())) {
      return false;
    }
    NotificationPolicy.Plan p = plan.get();
    List<MailGateway.Attachment> files = new ArrayList<>();
    if (p.attachmentWanted() && attachment != null) {
      try {
        // A missing object is RetryLater (retry topics), a hash mismatch NonRetryable (ADR-0009).
        byte[] bytes = documents.get(attachment);
        files.add(new MailGateway.Attachment(attachmentName, attachment.getContentType(), bytes));
      } catch (ClaimCheckExpiredException e) {
        log.warn("attachment for {} expired; sending without it", p.dedupeKey());
      }
    }
    Instant now = clock.instant();
    NotificationRepository.Sent sent =
        new NotificationRepository.Sent(
            ids.newId(),
            p.dedupeKey(),
            sourceEventId,
            p.template().id(),
            trigger.orderId(),
            contact.customerId(),
            CHANNEL,
            files.size(),
            now);
    if (!notifications.tryRecord(sent)) {
      return false;
    }
    mail.send(new MailGateway.Email(p.dedupeKey(), contact.email(), p.subject(), p.body(), files));
    outbox.append(NotificationMessages.sent(sent), causation);
    log.info(
        "sent {} notification {} with {} attachment(s)",
        p.template().id(),
        sent.notificationId(),
        files.size());
    return true;
  }

  /** Retention sweep for contact details. */
  @Transactional
  public int forgetExpiredContacts() {
    return contacts.deleteExpired(clock.instant());
  }
}
