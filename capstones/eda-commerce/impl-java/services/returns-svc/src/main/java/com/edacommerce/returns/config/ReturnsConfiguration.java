package com.edacommerce.returns.config;

import com.edacommerce.edacommon.consumer.MessageHandlerGroup;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.jobs.PeriodicJob;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import com.edacommerce.edacommon.saga.DeadlineSweeper;
import com.edacommerce.edacommon.saga.SagaEngine;
import com.edacommerce.edacommon.saga.SagaRepository;
import com.edacommerce.returns.adapters.in.messaging.ReturnsHandlers;
import com.edacommerce.returns.application.EligibilityRepository;
import com.edacommerce.returns.application.ReturnRepository;
import com.edacommerce.returns.application.ReturnsService;
import com.edacommerce.returns.application.SagaDataCodec;
import com.edacommerce.returns.domain.ReturnPolicy;
import java.time.Clock;
import java.time.Duration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.transaction.support.TransactionTemplate;

/** Composition root of returns-svc: the saga service, handlers, deadline sweeper. */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(ReturnsConfiguration.ReturnsProperties.class)
public class ReturnsConfiguration {

  /** RETURN_WINDOW_DAYS, RETURN_AUTO_APPROVE_LIMIT_MINOR, RETURN_PARCEL_DUE_DAYS (guide §7). */
  @ConfigurationProperties(prefix = "returns")
  public record ReturnsProperties(
      Integer windowDays,
      Long autoApproveLimitMinor,
      Integer parcelDueDays,
      String defaultWarehouseId,
      Duration sweepInterval) {
    public ReturnsProperties {
      windowDays = windowDays == null ? 30 : windowDays;
      autoApproveLimitMinor = autoApproveLimitMinor == null ? 50_000L : autoApproveLimitMinor;
      parcelDueDays = parcelDueDays == null ? 14 : parcelDueDays;
      defaultWarehouseId = defaultWarehouseId == null ? "wh-berlin-1" : defaultWarehouseId;
      sweepInterval = sweepInterval == null ? Duration.ofSeconds(5) : sweepInterval;
    }
  }

  @Bean
  ReturnsService returnsService(
      SagaEngine engine,
      EligibilityRepository eligibility,
      ReturnRepository returns,
      SagaDataCodec codec,
      IdGenerator ids,
      Clock clock,
      ReturnsProperties p) {
    return new ReturnsService(
        engine,
        eligibility,
        returns,
        codec,
        ids,
        clock,
        new ReturnPolicy(p.autoApproveLimitMinor(), Duration.ofDays(p.parcelDueDays())),
        Duration.ofDays(p.windowDays()),
        p.defaultWarehouseId());
  }

  @Bean
  MessageHandlerGroup returnsHandlers(ReturnsService returns) {
    return () -> ReturnsHandlers.all(returns);
  }

  @Bean
  DeadlineSweeper returnsDeadlineSweeper(
      SagaRepository repository,
      TransactionTemplate tx,
      ReturnsService returns,
      EdaMetrics metrics,
      Clock clock) {
    return new DeadlineSweeper(
        ReturnsService.SAGA_TYPE, repository, tx, returns::onDeadline, metrics, clock);
  }

  @Bean
  @ConditionalOnProperty(name = "eda.jobs.enabled", havingValue = "true", matchIfMissing = true)
  PeriodicJob returnsDeadlineSweeperJob(DeadlineSweeper sweeper, ReturnsProperties p) {
    return new PeriodicJob("returns-deadline-sweeper", p.sweepInterval(), sweeper::sweepOnce);
  }
}
