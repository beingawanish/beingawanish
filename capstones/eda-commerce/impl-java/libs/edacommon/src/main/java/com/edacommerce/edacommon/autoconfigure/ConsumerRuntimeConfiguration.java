package com.edacommerce.edacommon.autoconfigure;

import com.edacommerce.edacommon.config.EdaProperties;
import com.edacommerce.edacommon.consumer.ConsumerContainers;
import com.edacommerce.edacommon.consumer.DlqController;
import com.edacommerce.edacommon.consumer.DlqService;
import com.edacommerce.edacommon.consumer.FailureForwarder;
import com.edacommerce.edacommon.consumer.HandlerRegistry;
import com.edacommerce.edacommon.consumer.JitteredExponentialBackOff;
import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.consumer.RecordProcessor;
import com.edacommerce.edacommon.http.ReadinessCheck;
import com.edacommerce.edacommon.inbox.Inbox;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import com.edacommerce.edacommon.serde.AvroSerde;
import com.edacommerce.edacommon.tracing.MessagingTracing;
import java.time.Clock;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Conditional;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.core.ConsumerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.ConcurrentMessageListenerContainer;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * The consumer runtime (guide §4.1): enabled when the service subscribes to topics and {@code
 * eda.consumer.enabled} is true (tests switch it off to drive {@link RecordProcessor} directly).
 * Creates the main and retry containers, the failure forwarder and the DLQ endpoints.
 */
@Configuration(proxyBeanMethods = false)
@Conditional(OnConsumerTopicsCondition.class)
public class ConsumerRuntimeConfiguration {

  @Bean
  HandlerRegistry edaHandlerRegistry(
      org.springframework.beans.factory.ObjectProvider<MessageHandler<?>> handlers,
      org.springframework.beans.factory.ObjectProvider<
              com.edacommerce.edacommon.consumer.MessageHandlerGroup>
          groups) {
    return new HandlerRegistry(
        com.edacommerce.edacommon.consumer.MessageHandlerGroup.collect(
            handlers.orderedStream().toList(), groups.orderedStream().toList()));
  }

  @Bean
  RecordProcessor edaRecordProcessor(
      EdaProperties properties,
      HandlerRegistry handlers,
      Inbox inbox,
      AvroSerde serde,
      TransactionTemplate tx,
      MessagingTracing tracing,
      EdaMetrics metrics,
      Clock clock) {
    return new RecordProcessor(
        properties.getConsumerGroup(), handlers, inbox, serde, tx, tracing, metrics, clock);
  }

  @Bean
  FailureForwarder edaFailureForwarder(
      @Qualifier("edaKafkaTemplate") KafkaTemplate<String, byte[]> template,
      EdaProperties properties,
      EdaMetrics metrics,
      Clock clock) {
    return new FailureForwarder(template, properties.getConsumerGroup(), metrics, clock);
  }

  @Bean
  ConcurrentMessageListenerContainer<String, byte[]> edaMainContainer(
      @Qualifier("edaConsumerFactory") ConsumerFactory<String, byte[]> consumerFactory,
      EdaProperties properties,
      RecordProcessor processor,
      FailureForwarder forwarder) {
    ConcurrentMessageListenerContainer<String, byte[]> c =
        ConsumerContainers.main(
            consumerFactory,
            properties.getConsumer().getTopics(),
            processor,
            ConsumerContainers.errorHandler(forwarder, JitteredExponentialBackOff.adr0007()),
            properties.getConsumer().getConcurrency(),
            properties.getConsumer().getShutdownTimeout());
    c.setAutoStartup(properties.getConsumer().isAutoStartup());
    return c;
  }

  @Bean
  ConcurrentMessageListenerContainer<String, byte[]> edaRetryContainer(
      @Qualifier("edaConsumerFactory") ConsumerFactory<String, byte[]> consumerFactory,
      EdaProperties properties,
      RecordProcessor processor,
      FailureForwarder forwarder,
      Clock clock) {
    ConcurrentMessageListenerContainer<String, byte[]> c =
        ConsumerContainers.retry(
            consumerFactory,
            processor,
            ConsumerContainers.errorHandler(forwarder, JitteredExponentialBackOff.adr0007()),
            properties.getConsumer().getRetryConcurrency(),
            properties.getConsumer().getShutdownTimeout(),
            clock);
    c.setAutoStartup(properties.getConsumer().isAutoStartup());
    return c;
  }

  @Bean
  ReadinessCheck edaConsumerReadiness(
      @Qualifier("edaMainContainer") ConcurrentMessageListenerContainer<String, byte[]> main) {
    return new ReadinessCheck() {
      @Override
      public String name() {
        return "consumer";
      }

      @Override
      public boolean ready() {
        // Running means subscribed; an assignment may still be in progress, which is fine.
        return main.isRunning();
      }
    };
  }

  @Bean
  DlqService edaDlqService(
      EdaProperties properties,
      @Qualifier("edaConsumerFactory") ConsumerFactory<String, byte[]> consumerFactory,
      @Qualifier("edaKafkaTemplate") KafkaTemplate<String, byte[]> template,
      Clock clock) {
    return new DlqService(properties.getConsumerGroup(), consumerFactory, template, clock);
  }

  @Bean
  DlqController edaDlqController(DlqService dlq) {
    return new DlqController(dlq);
  }
}
