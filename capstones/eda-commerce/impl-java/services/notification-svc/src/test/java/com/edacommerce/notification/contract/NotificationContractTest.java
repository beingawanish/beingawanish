package com.edacommerce.notification.contract;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.notification.application.NotificationMessages;
import com.edacommerce.notification.application.NotificationRepository;
import com.edacommerce.order.InvoiceIssued;
import com.edacommerce.order.OrderCancelled;
import com.edacommerce.order.OrderConfirmed;
import com.edacommerce.order.OrderDelivered;
import com.edacommerce.order.OrderPlaced;
import com.edacommerce.order.OrderShipped;
import com.edacommerce.returns.ReturnAuthorized;
import com.edacommerce.returns.ReturnClosed;
import com.edacommerce.returns.ReturnRefunded;
import com.edacommerce.returns.ReturnRejected;
import com.edacommerce.shipping.ShipmentCreated;
import com.edacommerce.shipping.ShipmentException;
import java.time.Instant;
import org.junit.jupiter.api.Test;

/** Layer 2: golden messages this service consumes decode; what it produces validates. */
class NotificationContractTest {

  @Test
  void consumedMessagesDecodeFromTheirGoldenBytes() {
    assertThat(GoldenFixtures.assertSpecificRoundTrip(OrderPlaced.class).getContactEmail())
        .isNotBlank();
    GoldenFixtures.assertSpecificRoundTrip(OrderConfirmed.class);
    GoldenFixtures.assertSpecificRoundTrip(OrderCancelled.class);
    GoldenFixtures.assertSpecificRoundTrip(OrderShipped.class);
    GoldenFixtures.assertSpecificRoundTrip(InvoiceIssued.class);
    GoldenFixtures.assertSpecificRoundTrip(OrderDelivered.class);
    GoldenFixtures.assertSpecificRoundTrip(ShipmentCreated.class);
    GoldenFixtures.assertSpecificRoundTrip(ShipmentException.class);
    GoldenFixtures.assertSpecificRoundTrip(ReturnAuthorized.class);
    GoldenFixtures.assertSpecificRoundTrip(ReturnRejected.class);
    GoldenFixtures.assertSpecificRoundTrip(ReturnRefunded.class);
    GoldenFixtures.assertSpecificRoundTrip(ReturnClosed.class);
  }

  @Test
  void notificationSentValidatesAndIsKeyedByOrderOrCustomer() {
    Instant t = Instant.parse("2026-11-18T09:00:00Z");
    OutgoingMessage m =
        NotificationMessages.sent(
            new NotificationRepository.Sent(
                "n1", "invoice:i1", "e1", "invoice", "o1", "c1", "EMAIL", 1, t));
    assertThat(m.topic()).isEqualTo("notification.events.v1");
    assertThat(m.key()).isEqualTo("o1");
    GoldenFixtures.assertValidAgainstBundled(m.record());
    OutgoingMessage noOrder =
        NotificationMessages.sent(
            new NotificationRepository.Sent("n2", "k", "e2", "x", null, "c1", "EMAIL", 0, t));
    assertThat(noOrder.key()).isEqualTo("c1");
    GoldenFixtures.assertValidAgainstBundled(noOrder.record());
  }
}
