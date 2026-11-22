package com.edacommerce.catalog.adapters.in.messaging;

import com.edacommerce.catalog.application.CatalogUseCases;
import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.envelope.MessageContext;
import com.edacommerce.inventory.StockLevelChanged;

/** inventory.stock-level.v1: each record is a full snapshot; older versions are dropped. */
public record StockLevelHandler(CatalogUseCases useCases)
    implements MessageHandler<StockLevelChanged> {
  @Override
  public Class<StockLevelChanged> messageType() {
    return StockLevelChanged.class;
  }

  @Override
  public void handle(StockLevelChanged e, MessageContext ctx) {
    useCases.stockLevel(
        e.getSku(),
        e.getOnHand(),
        e.getReserved(),
        e.getAvailable(),
        e.getEnvelope().getAggregateVersion(),
        e.getAsOf());
  }
}
