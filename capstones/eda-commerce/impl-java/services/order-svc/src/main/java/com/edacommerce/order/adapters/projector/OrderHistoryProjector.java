package com.edacommerce.order.adapters.projector;

import com.edacommerce.common.ShipmentDirection;
import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.consumer.MessageHandlerGroup;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.envelope.MessageContext;
import com.edacommerce.edacommon.errors.RetryLaterException;
import com.edacommerce.kernel.Money;
import com.edacommerce.order.InvoiceIssued;
import com.edacommerce.order.OrderCancelled;
import com.edacommerce.order.OrderConfirmed;
import com.edacommerce.order.OrderDelivered;
import com.edacommerce.order.OrderPlaced;
import com.edacommerce.order.OrderRequiresAttention;
import com.edacommerce.order.OrderShipped;
import com.edacommerce.order.application.OrderView;
import com.edacommerce.order.domain.OrderStatus;
import com.edacommerce.returns.ReturnClosed;
import com.edacommerce.returns.ReturnOutcome;
import com.edacommerce.returns.ReturnRequested;
import java.util.ArrayList;
import java.util.List;
import java.util.function.BiConsumer;
import org.apache.avro.Schema;
import org.apache.avro.specific.SpecificRecord;

/**
 * The order-history projector (separate process, consumer group order-history-projector, ADR-0010).
 * Order events drive the summary under a version guard; every other event of the order's story adds a
 * timeline entry keyed by eventId.
 */
public class OrderHistoryProjector implements MessageHandlerGroup {
  private final JdbcOrderHistory history;

  public OrderHistoryProjector(JdbcOrderHistory history) {
    this.history = history;
  }

  /** A projection handler from a lambda. */
  record Projection<T extends SpecificRecord>(Class<T> messageType, BiConsumer<T, MessageContext> apply) implements MessageHandler<T> {
    @Override
    public void handle(T message, MessageContext context) {
      apply.accept(message, context);
    }
  }

  @Override
  public List<MessageHandler<?>> handlers() {
    List<MessageHandler<?>> h = new ArrayList<>();
    h.add(new Projection<>(OrderPlaced.class, (e, ctx) -> {
      Money total = Money.of(e.getTotal().getAmountMinor(), e.getTotal().getCurrency());
      List<OrderView.Line> lines = e.getLines().stream().map(l -> new OrderView.Line(l.getLineId(), l.getSku(), l.getProductName(),
          l.getQuantity(), Money.of(l.getUnitPrice().getAmountMinor(), l.getUnitPrice().getCurrency()),
          Money.of(l.getLineTotal().getAmountMinor(), l.getLineTotal().getCurrency()), 0)).toList();
      history.placed(e.getOrderId(), e.getCustomerId(), total, lines.stream().mapToInt(OrderView.Line::quantity).sum(), e.getPlacedAt(),
          version(e), lines);
      timeline(e, ctx, "Order placed");
    }));
    h.add(orderEvent(OrderConfirmed.class, OrderStatus.CONFIRMED, "Order confirmed"));
    h.add(new Projection<>(OrderCancelled.class, (e, ctx) -> {
      requireSummary(e.getOrderId());
      history.orderEvent(e.getOrderId(), version(e), OrderStatus.CANCELLED, e.getReason().name(), null, null, null);
      timeline(e, ctx, "Order cancelled: " + e.getReason());
    }));
    h.add(new Projection<>(OrderShipped.class, (e, ctx) -> {
      requireSummary(e.getOrderId());
      history.orderEvent(e.getOrderId(), version(e), OrderStatus.SHIPPED, null, e.getCarrier(), e.getTrackingNumber(), null);
      timeline(e, ctx, "Shipped with " + e.getCarrier());
    }));
    h.add(new Projection<>(InvoiceIssued.class, (e, ctx) -> {
      requireSummary(e.getOrderId());
      history.orderEvent(e.getOrderId(), version(e), null, null, null, null, Boolean.TRUE);
      timeline(e, ctx, "Invoice " + e.getInvoiceNumber());
    }));
    h.add(orderEvent(OrderDelivered.class, OrderStatus.DELIVERED, "Delivered"));
    h.add(orderEvent(OrderRequiresAttention.class, OrderStatus.NEEDS_ATTENTION, "Needs attention"));
    for (Class<? extends SpecificRecord> c : List.of(
        com.edacommerce.payment.PaymentAuthorized.class, com.edacommerce.payment.PaymentDeclined.class,
        com.edacommerce.payment.PaymentCaptured.class, com.edacommerce.payment.PaymentCaptureFailed.class,
        com.edacommerce.payment.PaymentVoided.class, com.edacommerce.payment.RefundFailed.class,
        com.edacommerce.fulfilment.FulfilmentAccepted.class, com.edacommerce.fulfilment.OrderPicked.class,
        com.edacommerce.fulfilment.OrderPacked.class, com.edacommerce.fulfilment.OrderDispatched.class,
        com.edacommerce.fulfilment.FulfilmentCancelled.class, com.edacommerce.fulfilment.FulfilmentFailed.class,
        com.edacommerce.fulfilment.ReturnReceived.class, com.edacommerce.fulfilment.ReturnInspected.class,
        com.edacommerce.shipping.ShipmentCreated.class, com.edacommerce.shipping.ShipmentException.class,
        com.edacommerce.returns.ReturnAuthorized.class, com.edacommerce.returns.ReturnRejected.class,
        com.edacommerce.returns.ReturnRefunded.class, com.edacommerce.notification.NotificationSent.class)) {
      h.add(timelineOnly(c));
    }
    h.add(new Projection<>(com.edacommerce.payment.RefundSucceeded.class, (e, ctx) -> {
      if (timeline(e, ctx, "Refund " + e.getAmount().getAmountMinor())) {
        history.refunded(e.getOrderId(), e.getAmount().getAmountMinor());
      }
    }));
    h.add(new Projection<>(com.edacommerce.shipping.ShipmentInTransit.class, (e, ctx) -> {
      if (timeline(e, ctx, "In transit") && e.getDirection() == ShipmentDirection.OUTBOUND) {
        history.shipmentStatus(e.getOrderId(), "IN_TRANSIT", 2);
      }
    }));
    h.add(new Projection<>(com.edacommerce.shipping.ShipmentDelivered.class, (e, ctx) -> {
      if (timeline(e, ctx, "Parcel delivered") && e.getDirection() == ShipmentDirection.OUTBOUND) {
        history.shipmentStatus(e.getOrderId(), "DELIVERED", 4);
      }
    }));
    h.add(new Projection<>(ReturnRequested.class, (e, ctx) -> {
      if (timeline(e, ctx, "Return requested")) {
        history.returnStatus(e.getOrderId(), OrderStatus.RETURN_IN_PROGRESS, true);
      }
    }));
    h.add(new Projection<>(ReturnClosed.class, (e, ctx) -> {
      if (timeline(e, ctx, "Return closed: " + e.getOutcome())) {
        OrderStatus s = e.getOutcome() == ReturnOutcome.REFUNDED ? OrderStatus.RETURNED
            : e.getOutcome() == ReturnOutcome.PARTIALLY_REFUNDED ? OrderStatus.PARTIALLY_RETURNED : OrderStatus.DELIVERED;
        history.returnStatus(e.getOrderId(), s, true);
      }
    }));
    return h;
  }

  private <T extends SpecificRecord> Projection<T> orderEvent(Class<T> type, OrderStatus status, String text) {
    return new Projection<>(type, (e, ctx) -> {
      String orderId = orderId(e);
      requireSummary(orderId);
      history.orderEvent(orderId, version(e), status, null, null, null, null);
      timeline(e, ctx, text);
    });
  }

  private <T extends SpecificRecord> Projection<T> timelineOnly(Class<T> type) {
    return new Projection<>(type, (e, ctx) -> timeline(e, ctx, null));
  }

  private void requireSummary(String orderId) {
    if (!history.exists(orderId)) {
      // OrderPlaced is first on order.events.v1; if it is in a retry topic, wait for it.
      throw new RetryLaterException("order " + orderId + " not projected yet");
    }
  }

  private boolean timeline(SpecificRecord e, MessageContext ctx, String description) {
    return history.timeline(ctx.eventId(), orderId(e), ctx.occurredAt(), kind(e.getSchema()), description);
  }

  static String orderId(SpecificRecord e) {
    Schema.Field f = e.getSchema().getField("orderId");
    Object v = e.get(f.pos());
    return v == null ? Envelopes.of(e).getPartitionKey() : v.toString();
  }

  static long version(SpecificRecord e) {
    return Envelopes.of(e).getAggregateVersion();
  }

  /** PaymentAuthorized -> PAYMENT_AUTHORIZED. */
  static String kind(Schema s) {
    return s.getName().replaceAll("([a-z])([A-Z])", "$1_$2").toUpperCase(java.util.Locale.ROOT);
  }
}
