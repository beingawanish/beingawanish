package com.edacommerce.order.contract;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.kernel.Money;
import com.edacommerce.order.application.OrderMessages;
import com.edacommerce.order.domain.CancellationReason;
import com.edacommerce.order.domain.Order;
import com.edacommerce.order.domain.OrderEvent;
import com.edacommerce.order.domain.OrderSagaCommand;
import com.edacommerce.order.domain.OrderSagaData;
import com.edacommerce.order.domain.OrderSagaState;
import java.time.Instant;
import java.util.List;
import org.apache.avro.specific.SpecificRecord;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class OrderContractTest {
  static final Instant T = Instant.parse("2026-11-18T09:00:00Z");

  @ParameterizedTest
  @ValueSource(strings = {
    "checkout.CheckoutSubmitted", "inventory.StockReserved", "inventory.StockReservationRejected", "inventory.ReservationCommitted",
    "inventory.ReservationReleased", "inventory.ReservationExpired", "payment.PaymentAuthorized", "payment.PaymentDeclined",
    "payment.PaymentVoided", "payment.PaymentCaptured", "payment.PaymentCaptureFailed", "fulfilment.FulfilmentAccepted",
    "fulfilment.OrderPacked", "fulfilment.OrderDispatched", "fulfilment.FulfilmentFailed", "fulfilment.FulfilmentCancelled",
    "shipping.ShipmentCreated", "shipping.ShipmentDelivered", "shipping.ShipmentException", "shipping.ShipmentInTransit",
    "order.OrderPlaced", "order.OrderConfirmed", "order.OrderCancelled", "order.OrderShipped", "order.OrderDelivered",
    "order.InvoiceIssued", "order.OrderRequiresAttention", "payment.RefundSucceeded", "returns.ReturnRequested",
    "returns.ReturnClosed", "notification.NotificationSent"})
  void consumedMessagesDecodeFromTheirGoldenBytes(String name) throws ClassNotFoundException {
    GoldenFixtures.assertSpecificRoundTrip(Class.forName("com.edacommerce." + name).asSubclass(SpecificRecord.class));
  }

  static Order order() {
    Money m = Money.of(12999, "EUR");
    return new Order("o1", "c1", "cust", List.of(new Order.OrderLine("l1", "SKU-1001", "Shoe", 1, m, m)), m, Money.zero("EUR"),
        Money.of(2075, "EUR"), m, new Order.PostalAddress("Jane", "Street 1", null, "Berlin", null, "10115", "DE", null),
        "jane@example.com", "STANDARD", "tok_visa_ok", T);
  }

  @Test
  void everyProducedCommandAndEventValidatesWithKeyAndTopic() {
    Order o = order();
    OrderSagaData d = new OrderSagaData();
    d.reservationId = "r";
    d.paymentId = "p";
    d.fulfilmentId = "f";
    d.shipmentId = "s";
    d.carrier = "c";
    d.trackingNumber = "t";
    for (OrderSagaCommand c : List.of(new OrderSagaCommand.ReserveStock("r", 900), new OrderSagaCommand.CommitReservation("r"),
        new OrderSagaCommand.ReleaseReservation("r", "x"), new OrderSagaCommand.AuthorizePayment("p"), new OrderSagaCommand.VoidPayment("p", "x"),
        new OrderSagaCommand.CapturePayment("p"), new OrderSagaCommand.RequestFulfilment("f", 2), new OrderSagaCommand.CancelFulfilment("f", "x"))) {
      OutgoingMessage m = OrderMessages.command(c, o, 3);
      assertThat(m.key()).isEqualTo("o1");
      assertThat(m.topic()).matches("(inventory|payment|fulfilment)\\.commands\\.v1");
      GoldenFixtures.assertValidAgainstBundled(m.record());
    }
    for (OrderEvent e : List.of(new OrderEvent.Placed(1), new OrderEvent.Confirmed(2),
        new OrderEvent.Cancelled(3, CancellationReason.PAYMENT_DECLINED, null, false), new OrderEvent.Shipped(4),
        new OrderEvent.Delivered(5, T, T), new OrderEvent.RequiresAttention(6, OrderSagaState.CAPTURING, "x"))) {
      OutgoingMessage m = OrderMessages.event(e, o, d, T);
      assertThat(m.topic()).isEqualTo("order.events.v1");
      assertThat(m.aggregateVersion()).isEqualTo(e.version());
      GoldenFixtures.assertValidAgainstBundled(m.record());
    }
  }
}
