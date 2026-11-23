package com.edacommerce.order.integration;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.config.EdaProperties;
import com.edacommerce.edacommon.consumer.HandlerRegistry;
import com.edacommerce.edacommon.testing.EdaServiceTest;
import com.edacommerce.order.adapters.in.http.OrderController;
import com.edacommerce.order.application.OrderSagaService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.TestPropertySource;

/** The projector process: own consumer group and topics, no saga, no Orders API (ADR-0010). */
@EdaServiceTest
@ActiveProfiles("projector")
@TestPropertySource(properties = {"eda.consumer.enabled=true", "eda.consumer.auto-startup=false"})
class ProjectorProfileIT {
  @Autowired ApplicationContext ctx;

  @Test
  void runsOnlyTheProjection() {
    assertThat(ctx.getBean(EdaProperties.class).getConsumerGroup())
        .isEqualTo("order-history-projector");
    assertThat(ctx.getBean(EdaProperties.class).getConsumer().getTopics())
        .contains("order.events.v1", "returns.events.v1", "notification.events.v1");
    assertThat(ctx.getBean(HandlerRegistry.class).types())
        .contains("com.edacommerce.order.OrderPlaced", "com.edacommerce.payment.RefundSucceeded");
    assertThat(ctx.getBeansOfType(OrderSagaService.class)).isEmpty();
    assertThat(ctx.getBeansOfType(OrderController.class)).isEmpty();
  }
}
