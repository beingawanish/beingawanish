package com.edacommerce.notification.adapters.in.messaging;

import com.edacommerce.common.ShipmentDirection;
import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.envelope.MessageContext;
import com.edacommerce.edacommon.errors.NonRetryableException;
import com.edacommerce.notification.application.NotificationUseCases;
import com.edacommerce.notification.domain.NotificationException;
import com.edacommerce.notification.domain.Trigger;
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
import java.util.List;
import java.util.function.BiConsumer;
import org.apache.avro.specific.SpecificRecord;

/**
 * The facts notification-svc listens to, mapped to domain triggers. Payment events are subscribed
 * (topics.yaml) but none needs a message of its own: refunds are announced by ReturnRefunded, so
 * the runtime ignores them.
 */
public final class NotificationHandlers {
  private NotificationHandlers() {}

  /** One message type mapped onto one use case. */
  public record Handler<T extends SpecificRecord>(
      Class<T> messageType, BiConsumer<T, MessageContext> body) implements MessageHandler<T> {
    @Override
    public void handle(T message, MessageContext ctx) {
      try {
        body.accept(message, ctx);
      } catch (NotificationException e) {
        throw new NonRetryableException(e.getMessage(), e);
      }
    }
  }

  public static List<MessageHandler<?>> all(NotificationUseCases u) {
    return List.of(
        new Handler<>(
            OrderPlaced.class,
            (e, ctx) ->
                u.rememberContact(
                    e.getOrderId(),
                    e.getCustomerId(),
                    e.getContactEmail(),
                    e.getShippingAddress().getRecipientName(),
                    e.getPlacedAt())),
        react(OrderConfirmed.class, e -> new Trigger.OrderConfirmed(e.getOrderId()), u),
        react(
            OrderCancelled.class,
            e -> new Trigger.OrderCancelled(e.getOrderId(), e.getReason().name()),
            u),
        react(
            OrderShipped.class,
            e ->
                new Trigger.OrderShipped(
                    e.getOrderId(), e.getShipmentId(), e.getCarrier(), e.getTrackingNumber()),
            u),
        new Handler<>(
            InvoiceIssued.class,
            (e, ctx) ->
                u.notify(
                    new Trigger.InvoiceIssued(
                        e.getOrderId(), e.getInvoiceId(), e.getInvoiceNumber()),
                    ctx.eventId(),
                    e.getDocument(),
                    e.getInvoiceNumber() + ".pdf",
                    ctx.causation())),
        react(
            OrderDelivered.class,
            e -> new Trigger.OrderDelivered(e.getOrderId(), e.getReturnWindowEndsAt()),
            u),
        new Handler<>(
            ShipmentCreated.class,
            (e, ctx) -> {
              if (e.getDirection() == ShipmentDirection.RETURN && e.getReturnId() != null) {
                u.notify(
                    new Trigger.ReturnLabelIssued(
                        e.getOrderId(), e.getReturnId(), e.getShipmentId(), e.getTrackingNumber()),
                    ctx.eventId(),
                    e.getLabel(),
                    "return-label-" + e.getTrackingNumber() + ".pdf",
                    ctx.causation());
              }
            }),
        react(
            ShipmentException.class,
            e ->
                new Trigger.ShipmentProblem(
                    e.getOrderId(),
                    e.getShipmentId(),
                    e.getDirection() == ShipmentDirection.OUTBOUND,
                    e.getCode().name()),
            u),
        react(
            ReturnAuthorized.class,
            e ->
                new Trigger.ReturnAuthorized(
                    e.getOrderId(), e.getReturnId(), e.getRmaNumber(), e.getParcelDueBy()),
            u),
        react(
            ReturnRejected.class,
            e -> new Trigger.ReturnRejected(e.getOrderId(), e.getReturnId(), e.getReason()),
            u),
        react(
            ReturnRefunded.class,
            e ->
                new Trigger.ReturnRefunded(
                    e.getOrderId(),
                    e.getReturnId(),
                    e.getAmount().getAmountMinor(),
                    e.getAmount().getCurrency()),
            u),
        react(
            ReturnClosed.class,
            e -> new Trigger.ReturnClosed(e.getOrderId(), e.getReturnId(), e.getOutcome().name()),
            u));
  }

  private static <T extends SpecificRecord> Handler<T> react(
      Class<T> type, java.util.function.Function<T, Trigger> trigger, NotificationUseCases u) {
    return new Handler<>(
        type, (e, ctx) -> u.notify(trigger.apply(e), ctx.eventId(), null, null, ctx.causation()));
  }
}
