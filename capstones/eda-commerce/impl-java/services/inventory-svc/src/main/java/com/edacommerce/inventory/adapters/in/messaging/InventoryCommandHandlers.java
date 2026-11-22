package com.edacommerce.inventory.adapters.in.messaging;

import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.envelope.MessageContext;
import com.edacommerce.edacommon.errors.NonRetryableException;
import com.edacommerce.edacommon.errors.RetryLaterException;
import com.edacommerce.inventory.CommitReservation;
import com.edacommerce.inventory.ReleaseReservation;
import com.edacommerce.inventory.ReserveStock;
import com.edacommerce.inventory.RestockItems;
import com.edacommerce.inventory.application.InventoryUseCases;
import com.edacommerce.inventory.domain.InventoryException;
import com.edacommerce.inventory.domain.StockLine;
import java.time.Clock;
import java.util.List;

/**
 * Handlers for inventory.commands.v1, registered by ce_type with the edacommon consumer runtime.
 * They translate contract messages into use-case calls and domain errors into NonRetryable; they
 * hold no business rules.
 */
public final class InventoryCommandHandlers {
  private InventoryCommandHandlers() {}

  static List<StockLine> lines(List<com.edacommerce.common.StockLine> lines) {
    try {
      return lines.stream().map(l -> new StockLine(l.getSku(), l.getQuantity())).toList();
    } catch (InventoryException e) {
      throw new NonRetryableException(e.getMessage(), e);
    }
  }

  /** ReserveStock. */
  public record Reserve(InventoryUseCases useCases, Clock clock)
      implements MessageHandler<ReserveStock> {
    @Override
    public Class<ReserveStock> messageType() {
      return ReserveStock.class;
    }

    @Override
    public void handle(ReserveStock cmd, MessageContext ctx) {
      try {
        useCases.reserve(
            cmd.getOrderId(),
            cmd.getReservationId(),
            lines(cmd.getLines()),
            cmd.getTtlSeconds(),
            ctx.isExpired(clock.instant()),
            ctx.causation());
      } catch (InventoryException e) {
        throw new NonRetryableException(e.getMessage(), e);
      }
    }
  }

  /**
   * CommitReservation. An unknown reservation is probably a ReserveStock still in a retry topic.
   */
  public record Commit(InventoryUseCases useCases) implements MessageHandler<CommitReservation> {
    @Override
    public Class<CommitReservation> messageType() {
      return CommitReservation.class;
    }

    @Override
    public void handle(CommitReservation cmd, MessageContext ctx) {
      if (useCases.commit(cmd.getReservationId(), ctx.causation()).isEmpty()) {
        throw new RetryLaterException("unknown reservation " + cmd.getReservationId());
      }
    }
  }

  /** ReleaseReservation (the saga's compensation). */
  public record Release(InventoryUseCases useCases) implements MessageHandler<ReleaseReservation> {
    @Override
    public Class<ReleaseReservation> messageType() {
      return ReleaseReservation.class;
    }

    @Override
    public void handle(ReleaseReservation cmd, MessageContext ctx) {
      useCases.release(cmd.getOrderId(), cmd.getReservationId(), cmd.getReason(), ctx.causation());
    }
  }

  /** RestockItems (returns saga). */
  public record Restock(InventoryUseCases useCases) implements MessageHandler<RestockItems> {
    @Override
    public Class<RestockItems> messageType() {
      return RestockItems.class;
    }

    @Override
    public void handle(RestockItems cmd, MessageContext ctx) {
      useCases.restock(
          cmd.getOrderId(),
          cmd.getReturnId(),
          cmd.getRestockId(),
          lines(cmd.getLines()),
          ctx.causation());
    }
  }
}
