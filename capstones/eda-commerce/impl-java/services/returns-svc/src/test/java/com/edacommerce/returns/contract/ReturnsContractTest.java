package com.edacommerce.returns.contract;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.fulfilment.FulfilmentAccepted;
import com.edacommerce.fulfilment.ReturnInspected;
import com.edacommerce.fulfilment.ReturnReceived;
import com.edacommerce.inventory.ItemsRestocked;
import com.edacommerce.order.OrderCancelled;
import com.edacommerce.order.OrderConfirmed;
import com.edacommerce.order.OrderDelivered;
import com.edacommerce.order.OrderPlaced;
import com.edacommerce.payment.RefundFailed;
import com.edacommerce.payment.RefundSucceeded;
import com.edacommerce.returns.application.ReturnMessages;
import com.edacommerce.returns.domain.InspectedItem;
import com.edacommerce.returns.domain.InspectionOutcome;
import com.edacommerce.returns.domain.Pickup;
import com.edacommerce.returns.domain.ReturnEvent;
import com.edacommerce.returns.domain.ReturnItem;
import com.edacommerce.returns.domain.ReturnOutcome;
import com.edacommerce.returns.domain.ReturnReason;
import com.edacommerce.returns.domain.ReturnSagaCommand;
import com.edacommerce.returns.domain.ReturnSagaData;
import com.edacommerce.shipping.ShipmentCreated;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/** Layer 2: golden messages this service consumes decode; everything it produces validates. */
class ReturnsContractTest {
  static final Instant T = Instant.parse("2026-11-18T09:00:00Z");

  @Test
  void consumedMessagesDecodeFromTheirGoldenBytes() {
    GoldenFixtures.assertSpecificRoundTrip(OrderPlaced.class);
    GoldenFixtures.assertSpecificRoundTrip(OrderConfirmed.class);
    GoldenFixtures.assertSpecificRoundTrip(OrderDelivered.class);
    GoldenFixtures.assertSpecificRoundTrip(OrderCancelled.class);
    GoldenFixtures.assertSpecificRoundTrip(FulfilmentAccepted.class);
    GoldenFixtures.assertSpecificRoundTrip(ReturnReceived.class);
    GoldenFixtures.assertSpecificRoundTrip(ReturnInspected.class);
    GoldenFixtures.assertSpecificRoundTrip(ItemsRestocked.class);
    GoldenFixtures.assertSpecificRoundTrip(RefundSucceeded.class);
    GoldenFixtures.assertSpecificRoundTrip(RefundFailed.class);
    GoldenFixtures.assertSpecificRoundTrip(ShipmentCreated.class);
  }

  @Test
  void everyProducedMessageValidatesAgainstTheBundledSchema() {
    ReturnSagaData d = new ReturnSagaData();
    d.returnId = "r1";
    d.orderId = "o1";
    d.customerId = "c1";
    d.paymentId = "p1";
    d.currency = "EUR";
    d.reason = ReturnReason.CHANGED_MIND;
    d.items = List.of(new ReturnItem("l1", "SKU-1", 2, 1000));
    d.requestedAt = T;
    d.rmaNumber = "RMA-2026-000001";
    d.parcelDueBy = T;
    d.warehouseId = "wh";
    d.refundId = "rf1";
    d.refundAmountMinor = 1000;
    d.inspected = List.of(new InspectedItem("l1", "SKU-1", 2, InspectionOutcome.RESTOCKABLE));
    List<OutgoingMessage> out =
        List.of(
            ReturnMessages.event(new ReturnEvent.Requested(1), d, T),
            ReturnMessages.event(new ReturnEvent.Authorized(2), d, T),
            ReturnMessages.event(new ReturnEvent.Rejected(3, "x"), d, T),
            ReturnMessages.event(new ReturnEvent.Refunded(4), d, T),
            ReturnMessages.event(
                new ReturnEvent.Closed(5, ReturnOutcome.PARTIALLY_REFUNDED), d, T));
    for (OutgoingMessage m : out) {
      assertThat(m.topic()).isEqualTo("returns.events.v1");
      assertThat(m.key()).isEqualTo("o1");
      assertThat(m.aggregateType()).isEqualTo("Return");
      GoldenFixtures.assertValidAgainstBundled(m.record());
    }
    Pickup pickup = new Pickup("Ada", "Main 1", null, "Berlin", null, "10115", "DE", null);
    Map<String, String> topics =
        Map.of(
            "IssueReturnLabel", "shipping.commands.v1",
            "ExpectReturn", "fulfilment.commands.v1",
            "RestockItems", "inventory.commands.v1",
            "RefundPayment", "payment.commands.v1");
    for (ReturnSagaCommand c :
        List.of(
            new ReturnSagaCommand.IssueReturnLabel("s1"),
            new ReturnSagaCommand.ExpectReturn(T),
            new ReturnSagaCommand.RestockItems("rs1", Map.of("SKU-1", 2)),
            new ReturnSagaCommand.RefundPayment("rf1", 1000))) {
      OutgoingMessage m = ReturnMessages.command(c, d, pickup, 3);
      assertThat(m.topic()).isEqualTo(topics.get(m.record().getSchema().getName()));
      assertThat(m.key()).isEqualTo("o1");
      assertThat(m.aggregateVersion()).isEqualTo(3);
      GoldenFixtures.assertValidAgainstBundled(m.record());
    }
  }
}
