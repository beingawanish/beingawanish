package com.edacommerce.order.config;

import com.edacommerce.edacommon.claimcheck.ClaimCheckStore;
import com.edacommerce.edacommon.consumer.MessageHandlerGroup;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.jobs.PeriodicJob;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import com.edacommerce.edacommon.saga.DeadlineSweeper;
import com.edacommerce.edacommon.saga.SagaEngine;
import com.edacommerce.edacommon.saga.SagaRepository;
import com.edacommerce.order.adapters.in.messaging.CheckoutSubmittedHandler;
import com.edacommerce.order.adapters.in.messaging.OrderSagaHandlers;
import com.edacommerce.order.adapters.out.documents.OpenPdfInvoiceRenderer;
import com.edacommerce.order.adapters.projector.JdbcOrderHistory;
import com.edacommerce.order.adapters.projector.OrderHistoryProjector;
import com.edacommerce.order.application.InvoiceRenderer;
import com.edacommerce.order.application.InvoiceRepository;
import com.edacommerce.order.application.OrderQueries;
import com.edacommerce.order.application.OrderRepository;
import com.edacommerce.order.application.OrderSagaService;
import com.edacommerce.order.application.SagaDataCodec;
import com.edacommerce.order.domain.SagaTimeouts;
import java.time.Clock;
import java.time.Duration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.transaction.support.TransactionTemplate;

/** Composition root of order-svc. The projector profile runs only the projection (ADR-0010). */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(OrderConfiguration.SagaProperties.class)
public class OrderConfiguration {

  /** SAGA_* step timeouts (guide §7). */
  @ConfigurationProperties(prefix = "order.saga")
  public record SagaProperties(Duration stockTimeout, Duration paymentTimeout, Duration commitTimeout, Duration fulfilmentAckTimeout,
      int fulfilmentMaxResends, Duration dispatchTimeout, Duration captureTimeout, Duration compensationTimeout, Duration sweepInterval) {
    SagaTimeouts timeouts() {
      return new SagaTimeouts(stockTimeout, paymentTimeout, commitTimeout, fulfilmentAckTimeout, fulfilmentMaxResends, dispatchTimeout,
          captureTimeout, compensationTimeout);
    }
  }

  @Bean
  OrderQueries orderQueries(JdbcOrderHistory history, OrderRepository orders, InvoiceRepository invoices, ClaimCheckStore documents) {
    return new OrderQueries(history, orders, invoices, documents);
  }

  /** The saga side: handlers, saga service, deadline sweeper. */
  @Configuration(proxyBeanMethods = false)
  @Profile("!projector")
  static class Saga {
    @Bean
    InvoiceRenderer invoiceRenderer() {
      return new OpenPdfInvoiceRenderer();
    }

    @Bean
    OrderSagaService orderSagaService(SagaEngine engine, OrderRepository orders, InvoiceRepository invoices, InvoiceRenderer renderer,
        ClaimCheckStore documents, SagaDataCodec codec, IdGenerator ids, SagaProperties properties, Clock clock) {
      return new OrderSagaService(engine, orders, invoices, renderer, documents, codec, ids::newId, properties.timeouts(), clock);
    }

    @Bean
    CheckoutSubmittedHandler checkoutSubmittedHandler(OrderSagaService saga) {
      return new CheckoutSubmittedHandler(saga);
    }

    @Bean
    MessageHandlerGroup orderSagaHandlers(OrderSagaService saga) {
      return () -> OrderSagaHandlers.all(saga);
    }

    @Bean
    DeadlineSweeper orderDeadlineSweeper(SagaRepository repository, TransactionTemplate tx, OrderSagaService saga, EdaMetrics metrics,
        Clock clock) {
      return new DeadlineSweeper(OrderSagaService.SAGA_TYPE, repository, tx, saga::onDeadline, metrics, clock);
    }

    @Bean
    @ConditionalOnProperty(name = "eda.jobs.enabled", havingValue = "true", matchIfMissing = true)
    PeriodicJob orderDeadlineSweeperJob(DeadlineSweeper sweeper, SagaProperties properties) {
      return new PeriodicJob("order-deadline-sweeper", properties.sweepInterval(), sweeper::sweepOnce);
    }
  }

  /** The order-history projector process. */
  @Configuration(proxyBeanMethods = false)
  @Profile("projector")
  static class Projector {
    @Bean
    OrderHistoryProjector orderHistoryProjector(JdbcOrderHistory history) {
      return new OrderHistoryProjector(history);
    }
  }
}
