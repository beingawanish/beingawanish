package com.edacommerce.inventory.config;

import com.edacommerce.edacommon.jobs.PeriodicJob;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.inventory.adapters.in.messaging.InventoryCommandHandlers;
import com.edacommerce.inventory.application.InventoryUseCases;
import com.edacommerce.inventory.application.ReservationRepository;
import com.edacommerce.inventory.application.RestockRepository;
import com.edacommerce.inventory.application.StockRepository;
import java.time.Clock;
import java.time.Duration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Composition root: wires ports to adapters and registers the handlers and jobs. */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(InventoryConfiguration.InventoryProperties.class)
public class InventoryConfiguration {

  /** RESERVATION_TTL and RESERVATION_SWEEP_INTERVAL (guide §7). */
  @ConfigurationProperties(prefix = "inventory")
  public record InventoryProperties(Duration reservationTtl, Duration reservationSweepInterval) {
    public InventoryProperties {
      reservationTtl = reservationTtl == null ? Duration.ofMinutes(15) : reservationTtl;
      reservationSweepInterval = reservationSweepInterval == null ? Duration.ofSeconds(5) : reservationSweepInterval;
    }
  }

  @Bean
  InventoryUseCases inventoryUseCases(
      ReservationRepository reservations,
      StockRepository stock,
      RestockRepository restocks,
      OutboxWriter outbox,
      Clock clock,
      InventoryProperties properties) {
    return new InventoryUseCases(reservations, stock, restocks, outbox, clock, properties.reservationTtl());
  }

  @Bean
  InventoryCommandHandlers.Reserve reserveStockHandler(InventoryUseCases useCases, Clock clock) {
    return new InventoryCommandHandlers.Reserve(useCases, clock);
  }

  @Bean
  InventoryCommandHandlers.Commit commitReservationHandler(InventoryUseCases useCases) {
    return new InventoryCommandHandlers.Commit(useCases);
  }

  @Bean
  InventoryCommandHandlers.Release releaseReservationHandler(InventoryUseCases useCases) {
    return new InventoryCommandHandlers.Release(useCases);
  }

  @Bean
  InventoryCommandHandlers.Restock restockItemsHandler(InventoryUseCases useCases) {
    return new InventoryCommandHandlers.Restock(useCases);
  }

  /** The TTL sweeper (ADR-0016), independent of the saga's own deadlines. */
  @Bean
  @ConditionalOnProperty(name = "eda.jobs.enabled", havingValue = "true", matchIfMissing = true)
  PeriodicJob reservationExpiryJob(InventoryUseCases useCases, InventoryProperties properties) {
    return new PeriodicJob("reservation-expiry", properties.reservationSweepInterval(), () -> useCases.expireDue(100));
  }
}
