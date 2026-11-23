package com.edacommerce.fulfilment.adapters.in.messaging;

import com.edacommerce.common.ShipmentDirection;
import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.envelope.MessageContext;
import com.edacommerce.edacommon.errors.NonRetryableException;
import com.edacommerce.fulfilment.CancelFulfilment;
import com.edacommerce.fulfilment.ExpectReturn;
import com.edacommerce.fulfilment.RequestFulfilment;
import com.edacommerce.fulfilment.application.FulfilmentMessages;
import com.edacommerce.fulfilment.application.FulfilmentUseCases;
import com.edacommerce.fulfilment.domain.FulfilmentException;
import com.edacommerce.fulfilment.domain.OrderLine;
import com.edacommerce.fulfilment.domain.ReturnLine;
import com.edacommerce.shipping.ShipmentCreated;
import com.edacommerce.shipping.ShipmentDelivered;
import java.time.Clock;
import java.util.List;
import java.util.function.BiConsumer;
import org.apache.avro.specific.SpecificRecord;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Handlers for fulfilment.commands.v1 and the shipping.events.v1 facts fulfilment reacts to. They
 * translate contract messages into use-case calls and domain errors into NonRetryable; they hold no
 * business rules. Types not listed (ShipmentInTransit, ShipmentException, IssueReturnLabel...) are
 * ignored by the runtime.
 */
public final class FulfilmentHandlers {
  private static final Logger log = LoggerFactory.getLogger(FulfilmentHandlers.class);

  private FulfilmentHandlers() {}

  /** One message type mapped onto one use case. */
  public record Handler<T extends SpecificRecord>(
      Class<T> messageType, BiConsumer<T, MessageContext> body) implements MessageHandler<T> {
    @Override
    public void handle(T message, MessageContext ctx) {
      try {
        body.accept(message, ctx);
      } catch (FulfilmentException e) {
        throw new NonRetryableException(e.getMessage(), e);
      }
    }
  }

  public static List<MessageHandler<?>> all(FulfilmentUseCases useCases, Clock clock) {
    return List.of(
        new Handler<>(
            RequestFulfilment.class,
            (cmd, ctx) -> {
              if (ctx.isExpired(clock.instant())) {
                log.warn("RequestFulfilment {} expired; not acted on", cmd.getFulfilmentId());
                return;
              }
              useCases.request(
                  cmd.getOrderId(),
                  cmd.getFulfilmentId(),
                  cmd.getLines().stream()
                      .map(
                          l ->
                              new OrderLine(
                                  l.getLineId(), l.getSku(), l.getProductName(), l.getQuantity()))
                      .toList(),
                  FulfilmentMessages.shipTo(cmd.getShipTo()),
                  cmd.getShippingMethod().name(),
                  cmd.getAttempt(),
                  ctx.causation());
            }),
        new Handler<>(
            CancelFulfilment.class,
            (cmd, ctx) ->
                useCases.cancel(cmd.getOrderId(), cmd.getFulfilmentId(), ctx.causation())),
        new Handler<>(
            ExpectReturn.class,
            (cmd, ctx) ->
                useCases.expectReturn(
                    cmd.getOrderId(),
                    cmd.getReturnId(),
                    cmd.getRmaNumber(),
                    cmd.getLines().stream()
                        .map(l -> new ReturnLine(l.getLineId(), l.getSku(), l.getQuantity()))
                        .toList(),
                    cmd.getExpectedBy())),
        new Handler<>(
            ShipmentCreated.class,
            (e, ctx) -> {
              if (e.getDirection() == ShipmentDirection.OUTBOUND && e.getFulfilmentId() != null) {
                useCases.dispatch(e.getFulfilmentId(), e.getShipmentId(), ctx.causation());
              }
            }),
        new Handler<>(
            ShipmentDelivered.class,
            (e, ctx) -> {
              if (e.getDirection() == ShipmentDirection.RETURN && e.getReturnId() != null) {
                useCases.returnDelivered(e.getReturnId(), ctx.causation());
              }
            }));
  }
}
