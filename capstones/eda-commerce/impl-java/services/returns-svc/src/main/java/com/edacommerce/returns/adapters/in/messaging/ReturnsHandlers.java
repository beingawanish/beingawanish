package com.edacommerce.returns.adapters.in.messaging;

import com.edacommerce.common.ShipmentDirection;
import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.envelope.MessageContext;
import com.edacommerce.edacommon.errors.NonRetryableException;
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
import com.edacommerce.returns.application.ReturnsService;
import com.edacommerce.returns.domain.InspectedItem;
import com.edacommerce.returns.domain.InspectionOutcome;
import com.edacommerce.returns.domain.LabelRef;
import com.edacommerce.returns.domain.OrderLine;
import com.edacommerce.returns.domain.ReturnSagaTrigger;
import com.edacommerce.returns.domain.ReturnsException;
import com.edacommerce.shipping.ShipmentCreated;
import java.util.List;
import java.util.function.BiConsumer;
import java.util.function.Function;
import org.apache.avro.specific.SpecificRecord;

/**
 * Everything returns-svc listens to: order facts for the eligibility view, and the replies and
 * events that move the returns saga (matched by returnId and business id). Messages without a
 * returnId (refunds of other flows, outbound shipments) are not for this saga and are skipped.
 */
public final class ReturnsHandlers {
  private ReturnsHandlers() {}

  /** One message type mapped onto one use case. */
  public record Handler<T extends SpecificRecord>(
      Class<T> messageType, BiConsumer<T, MessageContext> body) implements MessageHandler<T> {
    @Override
    public void handle(T message, MessageContext ctx) {
      try {
        body.accept(message, ctx);
      } catch (ReturnsException e) {
        throw new NonRetryableException(e.getMessage(), e);
      }
    }
  }

  public static List<MessageHandler<?>> all(ReturnsService s) {
    return List.of(
        new Handler<>(
            OrderPlaced.class,
            (e, ctx) ->
                s.orderPlaced(
                    e.getOrderId(),
                    e.getCustomerId(),
                    e.getTotal().getCurrency(),
                    e.getLines().stream()
                        .map(
                            l ->
                                new OrderLine(
                                    l.getLineId(),
                                    l.getSku(),
                                    l.getProductName(),
                                    l.getQuantity(),
                                    l.getUnitPrice().getAmountMinor()))
                        .toList(),
                    e.getTotal().getAmountMinor(),
                    ReturnMessages.pickup(e.getShippingAddress()),
                    ctx.envelope().getAggregateVersion())),
        new Handler<>(
            OrderConfirmed.class,
            (e, ctx) ->
                s.orderConfirmed(
                    e.getOrderId(), e.getPaymentId(), ctx.envelope().getAggregateVersion())),
        new Handler<>(
            OrderDelivered.class,
            (e, ctx) ->
                s.orderDelivered(
                    e.getOrderId(), e.getDeliveredAt(), ctx.envelope().getAggregateVersion())),
        new Handler<>(
            OrderCancelled.class,
            (e, ctx) -> s.orderCancelled(e.getOrderId(), ctx.envelope().getAggregateVersion())),
        new Handler<>(
            FulfilmentAccepted.class,
            (e, ctx) -> s.fulfilmentAccepted(e.getOrderId(), e.getWarehouseId())),
        saga(
            ShipmentCreated.class,
            e -> e.getDirection() == ShipmentDirection.RETURN ? e.getReturnId() : null,
            e ->
                new ReturnSagaTrigger.LabelIssued(
                    e.getShipmentId(),
                    new LabelRef(
                        e.getLabel().getBucket(),
                        e.getLabel().getObjectKey(),
                        e.getLabel().getContentType(),
                        e.getLabel().getSizeBytes(),
                        e.getLabel().getSha256(),
                        e.getLabel().getExpiresAt())),
            s),
        saga(
            ReturnReceived.class,
            ReturnReceived::getReturnId,
            e -> new ReturnSagaTrigger.ParcelReceived(),
            s),
        saga(
            ReturnInspected.class,
            ReturnInspected::getReturnId,
            e ->
                new ReturnSagaTrigger.Inspected(
                    e.getResults().stream()
                        .map(
                            r ->
                                new InspectedItem(
                                    r.getLineId(),
                                    r.getSku(),
                                    r.getQuantity(),
                                    outcome(r.getOutcome())))
                        .toList()),
            s),
        saga(
            ItemsRestocked.class,
            ItemsRestocked::getReturnId,
            e -> new ReturnSagaTrigger.ItemsRestocked(e.getRestockId()),
            s),
        saga(
            RefundSucceeded.class,
            RefundSucceeded::getReturnId,
            e -> new ReturnSagaTrigger.RefundSucceeded(e.getRefundId()),
            s),
        saga(
            RefundFailed.class,
            RefundFailed::getReturnId,
            e ->
                new ReturnSagaTrigger.RefundFailed(
                    e.getRefundId(), e.getRetryable(), e.getReason()),
            s));
  }

  /** Anti-corruption: an UNKNOWN outcome is treated as not restockable and not refundable. */
  static InspectionOutcome outcome(com.edacommerce.fulfilment.InspectionOutcome o) {
    return switch (o) {
      case RESTOCKABLE -> InspectionOutcome.RESTOCKABLE;
      case DAMAGED -> InspectionOutcome.DAMAGED;
      case MISSING, UNKNOWN -> InspectionOutcome.MISSING;
    };
  }

  private static <T extends SpecificRecord> Handler<T> saga(
      Class<T> type,
      Function<T, String> returnId,
      Function<T, ReturnSagaTrigger> trigger,
      ReturnsService s) {
    return new Handler<>(
        type,
        (e, ctx) -> {
          String id = returnId.apply(e);
          if (id != null) {
            s.handle(id, trigger.apply(e), ctx.eventType(), ctx.eventId(), ctx.causation());
          }
        });
  }
}
