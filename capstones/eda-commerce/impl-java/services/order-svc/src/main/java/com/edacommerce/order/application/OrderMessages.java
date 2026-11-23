package com.edacommerce.order.application;

import com.edacommerce.common.Address;
import com.edacommerce.common.ClaimCheck;
import com.edacommerce.common.LineItem;
import com.edacommerce.common.Money;
import com.edacommerce.common.ShippingMethod;
import com.edacommerce.common.StockLine;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.fulfilment.CancelFulfilment;
import com.edacommerce.fulfilment.RequestFulfilment;
import com.edacommerce.inventory.CommitReservation;
import com.edacommerce.inventory.ReleaseReservation;
import com.edacommerce.inventory.ReserveStock;
import com.edacommerce.order.InvoiceIssued;
import com.edacommerce.order.OrderCancelled;
import com.edacommerce.order.OrderConfirmed;
import com.edacommerce.order.OrderDelivered;
import com.edacommerce.order.OrderPlaced;
import com.edacommerce.order.OrderRequiresAttention;
import com.edacommerce.order.OrderShipped;
import com.edacommerce.order.domain.Invoice;
import com.edacommerce.order.domain.Order;
import com.edacommerce.order.domain.OrderEvent;
import com.edacommerce.order.domain.OrderSagaCommand;
import com.edacommerce.order.domain.OrderSagaData;
import com.edacommerce.payment.AuthorizePayment;
import com.edacommerce.payment.CapturePayment;
import com.edacommerce.payment.VoidPayment;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.apache.avro.specific.SpecificRecord;

/** Saga commands and order events -> contract messages, keyed by orderId (ADR-0005). */
public final class OrderMessages {
  private OrderMessages() {}

  public static final String ORDER_EVENTS = "order.events.v1";
  static final Map<Class<?>, String> COMMAND_TOPICS =
      Map.of(
          OrderSagaCommand.ReserveStock.class, "inventory.commands.v1",
          OrderSagaCommand.CommitReservation.class, "inventory.commands.v1",
          OrderSagaCommand.ReleaseReservation.class, "inventory.commands.v1",
          OrderSagaCommand.AuthorizePayment.class, "payment.commands.v1",
          OrderSagaCommand.VoidPayment.class, "payment.commands.v1",
          OrderSagaCommand.CapturePayment.class, "payment.commands.v1",
          OrderSagaCommand.RequestFulfilment.class, "fulfilment.commands.v1",
          OrderSagaCommand.CancelFulfilment.class, "fulfilment.commands.v1");

  public static Money money(com.edacommerce.kernel.Money m) {
    return new Money(m.amountMinor(), m.currency());
  }

  public static OutgoingMessage command(OrderSagaCommand c, Order o, long sagaVersion) {
    String id = o.orderId();
    SpecificRecord r =
        switch (c) {
          case OrderSagaCommand.ReserveStock x ->
              ReserveStock.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(id)
                  .setReservationId(x.reservationId())
                  .setTtlSeconds(x.ttlSeconds())
                  .setLines(
                      o.lines().stream().map(l -> new StockLine(l.sku(), l.quantity())).toList())
                  .build();
          case OrderSagaCommand.CommitReservation x ->
              CommitReservation.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(id)
                  .setReservationId(x.reservationId())
                  .build();
          case OrderSagaCommand.ReleaseReservation x ->
              ReleaseReservation.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(id)
                  .setReservationId(x.reservationId())
                  .setReason(x.reason())
                  .build();
          case OrderSagaCommand.AuthorizePayment x ->
              AuthorizePayment.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(id)
                  .setPaymentId(x.paymentId())
                  .setCustomerId(o.customerId())
                  .setAmount(money(o.total()))
                  .setPaymentMethodToken(o.paymentMethodToken())
                  .build();
          case OrderSagaCommand.VoidPayment x ->
              VoidPayment.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(id)
                  .setPaymentId(x.paymentId())
                  .setReason(x.reason())
                  .build();
          case OrderSagaCommand.CapturePayment x ->
              CapturePayment.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(id)
                  .setPaymentId(x.paymentId())
                  .setAmount(money(o.total()))
                  .build();
          case OrderSagaCommand.RequestFulfilment x ->
              RequestFulfilment.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(id)
                  .setFulfilmentId(x.fulfilmentId())
                  .setAttempt(x.attempt())
                  .setLines(lines(o))
                  .setShipTo(address(o.shippingAddress()))
                  .setShippingMethod(method(o.shippingMethod()))
                  .build();
          case OrderSagaCommand.CancelFulfilment x ->
              CancelFulfilment.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(id)
                  .setFulfilmentId(x.fulfilmentId())
                  .setReason(x.reason())
                  .build();
        };
    return OutgoingMessage.of(COMMAND_TOPICS.get(c.getClass()), id, r, "Order", id, sagaVersion);
  }

  /** Order events except InvoiceToIssue (see {@link #invoiceIssued}). */
  public static OutgoingMessage event(OrderEvent e, Order o, OrderSagaData d, Instant now) {
    String id = o.orderId();
    SpecificRecord r =
        switch (e) {
          case OrderEvent.Placed x ->
              OrderPlaced.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(id)
                  .setCustomerId(o.customerId())
                  .setLines(lines(o))
                  .setTotal(money(o.total()))
                  .setShippingAddress(address(o.shippingAddress()))
                  .setContactEmail(o.contactEmail())
                  .setShippingMethod(method(o.shippingMethod()))
                  .setPlacedAt(o.placedAt())
                  .build();
          case OrderEvent.Confirmed x ->
              OrderConfirmed.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(id)
                  .setReservationId(d.reservationId)
                  .setPaymentId(d.paymentId)
                  .setFulfilmentId(d.fulfilmentId)
                  .setConfirmedAt(now)
                  .build();
          case OrderEvent.Cancelled x ->
              OrderCancelled.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(id)
                  .setReason(com.edacommerce.order.CancellationReason.valueOf(x.reason().name()))
                  .setDetail(x.detail())
                  .setPaymentVoided(x.paymentVoided())
                  .setCancelledAt(now)
                  .build();
          case OrderEvent.Shipped x ->
              OrderShipped.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(id)
                  .setShipmentId(d.shipmentId)
                  .setCarrier(d.carrier)
                  .setTrackingNumber(d.trackingNumber)
                  .setCapturedAmount(money(d.capturedAmount == null ? o.total() : d.capturedAmount))
                  .setShippedAt(now)
                  .build();
          case OrderEvent.Delivered x ->
              OrderDelivered.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(id)
                  .setShipmentId(d.shipmentId)
                  .setDeliveredAt(x.deliveredAt())
                  .setReturnWindowEndsAt(x.returnWindowEndsAt())
                  .build();
          case OrderEvent.RequiresAttention x ->
              OrderRequiresAttention.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(id)
                  .setSagaState(x.state().name())
                  .setIssue(x.issue())
                  .setRaisedAt(now)
                  .build();
          case OrderEvent.InvoiceToIssue x ->
              throw new IllegalArgumentException("use invoiceIssued");
        };
    return OutgoingMessage.of(ORDER_EVENTS, id, r, "Order", id, e.version());
  }

  public static OutgoingMessage invoiceIssued(Invoice inv, ClaimCheck document, long version) {
    InvoiceIssued r =
        InvoiceIssued.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(inv.orderId())
            .setInvoiceId(inv.invoiceId())
            .setInvoiceNumber(inv.invoiceNumber())
            .setTotal(money(inv.total()))
            .setDocument(document)
            .setIssuedAt(inv.issuedAt())
            .build();
    return OutgoingMessage.of(ORDER_EVENTS, inv.orderId(), r, "Order", inv.orderId(), version);
  }

  static List<LineItem> lines(Order o) {
    return o.lines().stream()
        .map(
            l ->
                new LineItem(
                    l.lineId(),
                    l.sku(),
                    l.productName(),
                    l.quantity(),
                    money(l.unitPrice()),
                    money(l.lineTotal())))
        .toList();
  }

  static Address address(Order.PostalAddress a) {
    return new Address(
        a.recipientName(),
        a.line1(),
        a.line2(),
        a.city(),
        a.region(),
        a.postalCode(),
        a.countryCode(),
        a.phone());
  }

  static ShippingMethod method(String m) {
    try {
      return ShippingMethod.valueOf(m);
    } catch (IllegalArgumentException e) {
      return ShippingMethod.UNKNOWN;
    }
  }
}
