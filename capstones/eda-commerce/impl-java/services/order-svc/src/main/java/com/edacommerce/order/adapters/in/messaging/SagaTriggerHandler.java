package com.edacommerce.order.adapters.in.messaging;

import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.envelope.MessageContext;
import com.edacommerce.order.application.OrderSagaService;
import com.edacommerce.order.domain.OrderSagaTrigger;
import java.util.function.Function;
import org.apache.avro.specific.SpecificRecord;

/**
 * Feeds one participant reply type into the saga: extracts the orderId and maps the contract message
 * to a domain trigger (anti-corruption: enum UNKNOWN values map to "not for me").
 */
public record SagaTriggerHandler<T extends SpecificRecord>(
    Class<T> messageType, Function<T, String> orderId, Function<T, OrderSagaTrigger> trigger, OrderSagaService saga)
    implements MessageHandler<T> {

  @Override
  public void handle(T message, MessageContext ctx) {
    saga.handle(orderId.apply(message), trigger.apply(message), ctx.eventType(), ctx.eventId(), ctx.causation());
  }
}
