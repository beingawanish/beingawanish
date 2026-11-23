package com.edacommerce.edacommon.autoconfigure;

import com.edacommerce.edacommon.claimcheck.ClaimCheckStore;
import com.edacommerce.edacommon.claimcheck.S3ClaimCheckStore;
import com.edacommerce.edacommon.config.EdaProperties;
import com.edacommerce.edacommon.http.Caller;
import com.edacommerce.edacommon.http.HealthController;
import com.edacommerce.edacommon.http.ProblemHandler;
import com.edacommerce.edacommon.http.ReadinessCheck;
import com.edacommerce.edacommon.http.SecurityConfiguration;
import com.edacommerce.edacommon.idempotency.IdempotencyFilter;
import com.edacommerce.edacommon.idempotency.IdempotencyStore;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.inbox.Inbox;
import com.edacommerce.edacommon.jobs.PeriodicJob;
import com.edacommerce.edacommon.kafka.KafkaClients;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import com.edacommerce.edacommon.outbox.Housekeeping;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.edacommon.outbox.PollingOutboxRelay;
import com.edacommerce.edacommon.saga.SagaEngine;
import com.edacommerce.edacommon.saga.SagaOperator;
import com.edacommerce.edacommon.saga.SagaOpsController;
import com.edacommerce.edacommon.saga.SagaRepository;
import com.edacommerce.edacommon.serde.AvroSerde;
import com.edacommerce.edacommon.serde.HttpSchemaRegistryClient;
import com.edacommerce.edacommon.serde.SchemaRegistryClient;
import com.edacommerce.edacommon.tracing.MessagingTracing;
import io.opentelemetry.api.OpenTelemetry;
import java.time.Clock;
import java.time.Duration;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;
import org.springframework.boot.autoconfigure.jdbc.JdbcTemplateAutoConfiguration;
import org.springframework.boot.autoconfigure.orm.jpa.HibernateJpaAutoConfiguration;
import org.springframework.boot.autoconfigure.transaction.TransactionAutoConfiguration;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.kafka.core.ConsumerFactory;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.core.ProducerFactory;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Wires the shared library into a Spring Boot service. Everything a service needs to be a correct
 * participant (outbox, inbox, serde, tracing, metrics, idempotency, problem details, health,
 * security) is on by default; the consumer runtime is in {@link ConsumerRuntimeConfiguration}.
 */
@AutoConfiguration(
    after = {
      DataSourceAutoConfiguration.class,
      JdbcTemplateAutoConfiguration.class,
      HibernateJpaAutoConfiguration.class,
      TransactionAutoConfiguration.class
    })
@EnableConfigurationProperties(EdaProperties.class)
@Import({SecurityConfiguration.class, ConsumerRuntimeConfiguration.class})
public class EdaCommonAutoConfiguration {

  @Bean
  @ConditionalOnMissingBean
  Clock edaClock() {
    return Clock.systemUTC();
  }

  @Bean
  @ConditionalOnMissingBean
  IdGenerator edaIdGenerator() {
    return IdGenerator.uuidV7();
  }

  @Bean
  @ConditionalOnMissingBean
  OpenTelemetry edaOpenTelemetryFallback() {
    return OpenTelemetry.noop();
  }

  @Bean
  @ConditionalOnMissingBean
  EdaMetrics edaMetrics(OpenTelemetry openTelemetry) {
    return new EdaMetrics(openTelemetry);
  }

  @Bean
  @ConditionalOnMissingBean
  MessagingTracing edaMessagingTracing(OpenTelemetry openTelemetry) {
    return new MessagingTracing(openTelemetry);
  }

  @Bean
  @ConditionalOnMissingBean
  SchemaRegistryClient edaSchemaRegistryClient(EdaProperties properties) {
    return new HttpSchemaRegistryClient(properties.getSchemaRegistryUrl());
  }

  @Bean
  @ConditionalOnMissingBean
  AvroSerde edaAvroSerde(SchemaRegistryClient registry) {
    return new AvroSerde(registry);
  }

  @Bean
  @ConditionalOnMissingBean
  TransactionTemplate edaTransactionTemplate(PlatformTransactionManager transactionManager) {
    return new TransactionTemplate(transactionManager);
  }

  @Bean
  @ConditionalOnMissingBean
  OutboxWriter edaOutboxWriter(
      JdbcTemplate jdbc, AvroSerde serde, Clock clock, IdGenerator ids, EdaProperties properties) {
    return new OutboxWriter(jdbc, serde, clock, ids, properties.getServiceName());
  }

  @Bean
  @ConditionalOnMissingBean
  Inbox edaInbox(JdbcTemplate jdbc) {
    return new Inbox(jdbc);
  }

  @Bean
  @ConditionalOnMissingBean
  SagaRepository edaSagaRepository(JdbcTemplate jdbc) {
    return new SagaRepository(jdbc);
  }

  @Bean
  @ConditionalOnMissingBean
  SagaEngine edaSagaEngine(
      SagaRepository repository,
      OutboxWriter outbox,
      TransactionTemplate tx,
      EdaMetrics metrics,
      Clock clock) {
    return new SagaEngine(repository, outbox, tx, metrics, clock);
  }

  @Bean
  @ConditionalOnBean(SagaOperator.class)
  SagaOpsController edaSagaOpsController(SagaRepository repository, SagaOperator operator) {
    return new SagaOpsController(repository, operator);
  }

  @Bean
  @ConditionalOnMissingBean
  Caller edaCaller(EdaProperties properties) {
    return new Caller(properties);
  }

  @Bean
  @ConditionalOnMissingBean
  IdempotencyStore edaIdempotencyStore(JdbcTemplate jdbc) {
    return new IdempotencyStore(jdbc);
  }

  @Bean
  FilterRegistrationBean<IdempotencyFilter> edaIdempotencyFilter(
      IdempotencyStore store,
      TransactionTemplate tx,
      Caller caller,
      EdaProperties properties,
      Clock clock) {
    FilterRegistrationBean<IdempotencyFilter> registration =
        new FilterRegistrationBean<>(
            new IdempotencyFilter(
                store,
                tx,
                caller,
                properties.getIdempotency().getPaths(),
                properties.getIdempotency().getTtl(),
                clock));
    // After Spring Security (order -100), so the caller is known.
    registration.setOrder(0);
    return registration;
  }

  @Bean
  ProblemHandler edaProblemHandler() {
    return new ProblemHandler();
  }

  @Bean
  HealthController edaHealthController(ObjectProvider<ReadinessCheck> checks) {
    return new HealthController(checks.orderedStream().toList());
  }

  @Bean
  ReadinessCheck edaDatabaseReadiness(JdbcTemplate jdbc) {
    return new ReadinessCheck() {
      @Override
      public String name() {
        return "database";
      }

      @Override
      public boolean ready() {
        Integer one = jdbc.queryForObject("SELECT 1", Integer.class);
        return one != null && one == 1;
      }
    };
  }

  @Bean
  ReadinessCheck edaSchemaRegistryReadiness(SchemaRegistryClient registry) {
    return new ReadinessCheck() {
      @Override
      public String name() {
        return "schemaRegistry";
      }

      @Override
      public boolean ready() {
        return registry.isWarm() || registry.ping();
      }
    };
  }

  @Bean
  @ConditionalOnMissingBean
  ClaimCheckStore edaClaimCheckStore(EdaProperties properties, EdaMetrics metrics, Clock clock) {
    return S3ClaimCheckStore.fromProperties(properties.getS3(), metrics, clock);
  }

  @Bean
  @ConditionalOnMissingBean(name = "edaProducerFactory")
  ProducerFactory<String, byte[]> edaProducerFactory(EdaProperties properties) {
    return new DefaultKafkaProducerFactory<>(KafkaClients.producer(properties.getKafka()));
  }

  @Bean
  @ConditionalOnMissingBean(name = "edaKafkaTemplate")
  KafkaTemplate<String, byte[]> edaKafkaTemplate(
      ProducerFactory<String, byte[]> edaProducerFactory) {
    KafkaTemplate<String, byte[]> template = new KafkaTemplate<>(edaProducerFactory);
    template.setObservationEnabled(false);
    return template;
  }

  @Bean
  @ConditionalOnMissingBean(name = "edaConsumerFactory")
  ConsumerFactory<String, byte[]> edaConsumerFactory(EdaProperties properties) {
    return new DefaultKafkaConsumerFactory<>(KafkaClients.consumer(properties.getKafka()));
  }

  @Bean
  @ConditionalOnProperty(name = "eda.outbox-relay", havingValue = "polling")
  PollingOutboxRelay edaPollingOutboxRelay(
      JdbcTemplate jdbc,
      TransactionTemplate tx,
      KafkaTemplate<String, byte[]> edaKafkaTemplate,
      EdaMetrics metrics) {
    return new PollingOutboxRelay(jdbc, tx, edaKafkaTemplate, metrics, 100);
  }

  @Bean
  @ConditionalOnProperty(name = "eda.outbox-relay", havingValue = "polling")
  PeriodicJob edaPollingOutboxRelayJob(PollingOutboxRelay relay, EdaProperties properties) {
    return new PeriodicJob("outbox-relay", properties.getOutboxPollInterval(), relay::relayOnce);
  }

  @Bean
  @ConditionalOnProperty(
      name = "eda.housekeeping.enabled",
      havingValue = "true",
      matchIfMissing = true)
  PeriodicJob edaHousekeepingJob(JdbcTemplate jdbc) {
    Housekeeping housekeeping = new Housekeeping(jdbc);
    return new PeriodicJob("housekeeping", Duration.ofHours(1), housekeeping::run);
  }
}
