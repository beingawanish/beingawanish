package com.edacommerce.shipping.adapters.in.messaging;

import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.envelope.MessageContext;
import com.edacommerce.edacommon.errors.NonRetryableException;
import com.edacommerce.fulfilment.OrderPacked;
import com.edacommerce.shipping.IssueReturnLabel;
import com.edacommerce.shipping.application.ShippingMessages;
import com.edacommerce.shipping.application.ShippingUseCases;
import com.edacommerce.shipping.domain.ShippingException;
import java.util.List;
import java.util.function.BiConsumer;
import org.apache.avro.specific.SpecificRecord;

/**
 * Handlers for the fulfilment.events.v1 fact shipping reacts to (OrderPacked, choreography) and for
 * shipping.commands.v1. Every other fulfilment event is ignored by the runtime.
 */
public final class ShippingHandlers {
  private ShippingHandlers() {}

  /** One message type mapped onto one use case. */
  public record Handler<T extends SpecificRecord>(
      Class<T> messageType, BiConsumer<T, MessageContext> body) implements MessageHandler<T> {
    @Override
    public void handle(T message, MessageContext ctx) {
      try {
        body.accept(message, ctx);
      } catch (ShippingException e) {
        throw new NonRetryableException(e.getMessage(), e);
      }
    }
  }

  public static List<MessageHandler<?>> all(ShippingUseCases useCases) {
    return List.of(
        new Handler<>(
            OrderPacked.class,
            (e, ctx) ->
                useCases.onOrderPacked(
                    e.getOrderId(),
                    e.getFulfilmentId(),
                    e.getWarehouseId(),
                    ShippingMessages.address(e.getShipTo()),
                    e.getShippingMethod().name(),
                    e.getParcels().size(),
                    ctx.causation())),
        new Handler<>(
            IssueReturnLabel.class,
            (cmd, ctx) ->
                useCases.issueReturnLabel(
                    cmd.getOrderId(),
                    cmd.getReturnId(),
                    cmd.getShipmentId(),
                    ShippingMessages.address(cmd.getPickupFrom()),
                    cmd.getToWarehouseId(),
                    ctx.causation())));
  }
}
