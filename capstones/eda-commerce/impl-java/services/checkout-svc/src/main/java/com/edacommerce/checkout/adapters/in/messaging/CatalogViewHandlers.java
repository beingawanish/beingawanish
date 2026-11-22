package com.edacommerce.checkout.adapters.in.messaging;

import com.edacommerce.catalog.PriceChanged;
import com.edacommerce.catalog.ProductStatus;
import com.edacommerce.catalog.ProductUpserted;
import com.edacommerce.checkout.application.CheckoutPorts;
import com.edacommerce.checkout.application.CheckoutUseCases;
import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.consumer.MessageHandlerGroup;
import com.edacommerce.edacommon.envelope.MessageContext;
import com.edacommerce.inventory.StockLevelChanged;
import com.edacommerce.kernel.Money;
import com.edacommerce.order.OrderCancelled;
import com.edacommerce.order.OrderPlaced;
import java.util.List;
import java.util.function.BiConsumer;
import org.apache.avro.specific.SpecificRecord;

/**
 * Builds the catalog read model from the compacted topics (each record a full snapshot, applied
 * only if its aggregateVersion is newer) and records order outcomes on the checkout row.
 * ProductStatus.UNKNOWN (a status this build does not know) is treated as not sellable.
 */
public record CatalogViewHandlers(CheckoutPorts.CatalogView view, CheckoutUseCases useCases)
    implements MessageHandlerGroup {

  record H<T extends SpecificRecord>(Class<T> messageType, BiConsumer<T, MessageContext> apply)
      implements MessageHandler<T> {
    @Override
    public void handle(T m, MessageContext ctx) {
      apply.accept(m, ctx);
    }
  }

  @Override
  public List<MessageHandler<?>> handlers() {
    return List.of(
        new H<>(
            ProductUpserted.class,
            (p, ctx) ->
                view.applyProduct(
                    p.getSku(),
                    p.getName(),
                    p.getStatus() == ProductStatus.ACTIVE,
                    p.getEnvelope().getAggregateVersion(),
                    ctx.occurredAt())),
        new H<>(
            PriceChanged.class,
            (p, ctx) ->
                view.applyPrice(
                    p.getSku(),
                    money(p.getListPrice()),
                    p.getSalePrice() == null ? null : money(p.getSalePrice()),
                    p.getEnvelope().getAggregateVersion(),
                    ctx.occurredAt())),
        new H<>(
            StockLevelChanged.class,
            (s, ctx) ->
                view.applyStock(
                    s.getSku(),
                    s.getAvailable(),
                    s.getEnvelope().getAggregateVersion(),
                    ctx.occurredAt())),
        new H<>(
            OrderPlaced.class, (o, ctx) -> useCases.orderOutcome(o.getOrderId(), "ORDER_PLACED")),
        new H<>(
            OrderCancelled.class,
            (o, ctx) -> useCases.orderOutcome(o.getOrderId(), "ORDER_CANCELLED")));
  }

  static Money money(com.edacommerce.common.Money m) {
    return Money.of(m.getAmountMinor(), m.getCurrency());
  }
}
