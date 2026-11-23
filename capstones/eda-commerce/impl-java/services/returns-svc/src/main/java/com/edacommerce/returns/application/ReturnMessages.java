package com.edacommerce.returns.application;

import com.edacommerce.common.Address;
import com.edacommerce.common.Money;
import com.edacommerce.common.ReturnLine;
import com.edacommerce.common.StockLine;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.fulfilment.ExpectReturn;
import com.edacommerce.inventory.RestockItems;
import com.edacommerce.payment.RefundPayment;
import com.edacommerce.returns.ReturnAuthorized;
import com.edacommerce.returns.ReturnClosed;
import com.edacommerce.returns.ReturnOutcome;
import com.edacommerce.returns.ReturnReason;
import com.edacommerce.returns.ReturnRefunded;
import com.edacommerce.returns.ReturnRejected;
import com.edacommerce.returns.ReturnRequested;
import com.edacommerce.returns.domain.Pickup;
import com.edacommerce.returns.domain.ReturnEvent;
import com.edacommerce.returns.domain.ReturnSagaCommand;
import com.edacommerce.returns.domain.ReturnSagaData;
import com.edacommerce.shipping.IssueReturnLabel;
import java.time.Instant;
import java.util.List;
import org.apache.avro.specific.SpecificRecord;

/**
 * Saga commands and return events -> contract messages, all keyed by orderId so a return's messages
 * stay in order with the order's (topics.yaml "Per orderId, which also orders several returns of
 * the same order").
 */
public final class ReturnMessages {
  private ReturnMessages() {}

  public static final String EVENTS = "returns.events.v1";

  public static OutgoingMessage event(ReturnEvent e, ReturnSagaData d, Instant now) {
    SpecificRecord r =
        switch (e) {
          case ReturnEvent.Requested x ->
              ReturnRequested.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(d.orderId)
                  .setReturnId(d.returnId)
                  .setCustomerId(d.customerId)
                  .setLines(returnLines(d))
                  .setReason(ReturnReason.valueOf(d.reason.name()))
                  .setComment(d.comment)
                  .setRequestedAt(d.requestedAt)
                  .build();
          case ReturnEvent.Authorized x ->
              ReturnAuthorized.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(d.orderId)
                  .setReturnId(d.returnId)
                  .setRmaNumber(d.rmaNumber)
                  .setAuthorizedAt(now)
                  .setParcelDueBy(d.parcelDueBy)
                  .build();
          case ReturnEvent.Rejected x ->
              ReturnRejected.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(d.orderId)
                  .setReturnId(d.returnId)
                  .setReason(x.reason())
                  .setRejectedAt(now)
                  .build();
          case ReturnEvent.Refunded x ->
              ReturnRefunded.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(d.orderId)
                  .setReturnId(d.returnId)
                  .setRefundId(d.refundId)
                  .setAmount(new Money(d.refundAmountMinor, d.currency))
                  .setRefundedAt(now)
                  .build();
          case ReturnEvent.Closed x ->
              ReturnClosed.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(d.orderId)
                  .setReturnId(d.returnId)
                  .setOutcome(ReturnOutcome.valueOf(x.outcome().name()))
                  .setClosedAt(now)
                  .build();
        };
    return OutgoingMessage.of(EVENTS, d.orderId, r, "Return", d.returnId, e.version());
  }

  /**
   * @param pickup the customer's address, from the eligibility view (kept out of saga data)
   * @param sagaVersion commands carry the saga row version
   */
  public static OutgoingMessage command(
      ReturnSagaCommand c, ReturnSagaData d, Pickup pickup, long sagaVersion) {
    SpecificRecord r;
    String topic;
    switch (c) {
      case ReturnSagaCommand.IssueReturnLabel x -> {
        topic = "shipping.commands.v1";
        r =
            IssueReturnLabel.newBuilder()
                .setEnvelope(Envelopes.placeholder())
                .setOrderId(d.orderId)
                .setReturnId(d.returnId)
                .setShipmentId(x.shipmentId())
                .setPickupFrom(address(pickup))
                .setToWarehouseId(d.warehouseId)
                .build();
      }
      case ReturnSagaCommand.ExpectReturn x -> {
        topic = "fulfilment.commands.v1";
        r =
            ExpectReturn.newBuilder()
                .setEnvelope(Envelopes.placeholder())
                .setOrderId(d.orderId)
                .setReturnId(d.returnId)
                .setRmaNumber(d.rmaNumber)
                .setLines(returnLines(d))
                .setExpectedBy(x.expectedBy())
                .build();
      }
      case ReturnSagaCommand.RestockItems x -> {
        topic = "inventory.commands.v1";
        r =
            RestockItems.newBuilder()
                .setEnvelope(Envelopes.placeholder())
                .setOrderId(d.orderId)
                .setReturnId(d.returnId)
                .setRestockId(x.restockId())
                .setLines(
                    x.lines().entrySet().stream()
                        .map(en -> new StockLine(en.getKey(), en.getValue()))
                        .toList())
                .build();
      }
      case ReturnSagaCommand.RefundPayment x -> {
        topic = "payment.commands.v1";
        r =
            RefundPayment.newBuilder()
                .setEnvelope(Envelopes.placeholder())
                .setOrderId(d.orderId)
                .setPaymentId(d.paymentId)
                .setRefundId(x.refundId())
                .setReturnId(d.returnId)
                .setAmount(new Money(x.amountMinor(), d.currency))
                .setReason("return " + d.rmaNumber)
                .build();
      }
    }
    return OutgoingMessage.of(topic, d.orderId, r, "Return", d.returnId, sagaVersion);
  }

  static List<ReturnLine> returnLines(ReturnSagaData d) {
    return d.items.stream().map(i -> new ReturnLine(i.lineId(), i.sku(), i.quantity())).toList();
  }

  static Address address(Pickup p) {
    return Address.newBuilder()
        .setRecipientName(p.recipientName())
        .setLine1(p.line1())
        .setLine2(p.line2())
        .setCity(p.city())
        .setRegion(p.region())
        .setPostalCode(p.postalCode())
        .setCountryCode(p.countryCode())
        .setPhone(p.phone())
        .build();
  }

  public static Pickup pickup(Address a) {
    return new Pickup(
        a.getRecipientName(),
        a.getLine1(),
        a.getLine2(),
        a.getCity(),
        a.getRegion(),
        a.getPostalCode(),
        a.getCountryCode(),
        a.getPhone());
  }
}
