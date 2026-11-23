package com.edacommerce.fulfilment.config;

import com.edacommerce.edacommon.claimcheck.ClaimCheckStore;
import com.edacommerce.edacommon.consumer.MessageHandlerGroup;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.jobs.PeriodicJob;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.fulfilment.adapters.in.messaging.FulfilmentHandlers;
import com.edacommerce.fulfilment.adapters.out.wms.fake.FakeWms;
import com.edacommerce.fulfilment.adapters.out.wms.fake.FakeWmsConfig;
import com.edacommerce.fulfilment.application.FulfilmentRepository;
import com.edacommerce.fulfilment.application.FulfilmentUseCases;
import com.edacommerce.fulfilment.application.ReturnIntakeRepository;
import java.time.Clock;
import java.time.Duration;
import java.util.Random;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.transaction.support.TransactionTemplate;

/** Composition root of fulfilment-svc: ports to adapters, handlers, the fake WMS and its job. */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(FulfilmentConfiguration.FulfilmentProperties.class)
public class FulfilmentConfiguration {

  /** FAKE_WMS_* (admin.yaml FakeWmsConfig, upper snake case) and the fake's tick interval. */
  @ConfigurationProperties(prefix = "fulfilment")
  public record FulfilmentProperties(Duration wmsTickInterval, FakeWmsConfig fakeWms) {
    public FulfilmentProperties {
      wmsTickInterval = wmsTickInterval == null ? Duration.ofMillis(500) : wmsTickInterval;
      fakeWms = FakeWmsConfig.DEFAULTS.merge(fakeWms == null ? FakeWmsConfig.DEFAULTS : fakeWms);
    }
  }

  @Bean
  FakeWms fakeWms(FulfilmentProperties properties, Clock clock, IdGenerator ids) {
    return new FakeWms(properties.fakeWms(), clock, ids, new Random());
  }

  @Bean
  FulfilmentUseCases fulfilmentUseCases(
      FulfilmentRepository fulfilments,
      ReturnIntakeRepository intakes,
      FakeWms warehouse,
      ClaimCheckStore documents,
      OutboxWriter outbox,
      TransactionTemplate tx,
      Clock clock) {
    return new FulfilmentUseCases(fulfilments, intakes, warehouse, documents, outbox, tx, clock);
  }

  @Bean
  MessageHandlerGroup fulfilmentHandlers(FulfilmentUseCases useCases, Clock clock) {
    return () -> FulfilmentHandlers.all(useCases, clock);
  }

  /** Drives the fake warehouse's progress (accept, pick, pack, inspect) on the clock. */
  @Bean
  @ConditionalOnProperty(name = "eda.jobs.enabled", havingValue = "true", matchIfMissing = true)
  PeriodicJob fakeWmsJob(FakeWms wms, FulfilmentUseCases useCases, FulfilmentProperties p) {
    return new PeriodicJob("fake-wms", p.wmsTickInterval(), () -> wms.tick(useCases));
  }
}
