package com.edacommerce.payment.application;

import com.edacommerce.payment.domain.Payment;
import java.util.List;

/**
 * Port: webhooks stored by the endpoint (store-then-ack) and not yet applied. The adapter maps the
 * PSP vocabulary to these normalised notifications.
 */
public interface PspNotifications {

  /** A stored notification, normalised. */
  sealed interface Stored {
    String pspEventId();

    record ForPayment(String pspEventId, String paymentId, Payment.Notification notification) implements Stored {}

    record ForRefund(String pspEventId, String refundId, boolean succeeded, String pspReference, String failure, boolean retryable)
        implements Stored {}

    /** Something we do not act on (e.g. void.succeeded, unknown types). */
    record Ignored(String pspEventId) implements Stored {}
  }

  List<Stored> lockUnprocessed(int limit);

  void markProcessed(String pspEventId);
}
