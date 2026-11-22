package com.edacommerce.notification.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.edacommerce.edacommon.consumer.DlqController;
import com.edacommerce.edacommon.consumer.HandlerRegistry;
import com.edacommerce.edacommon.jobs.PeriodicJob;
import com.edacommerce.edacommon.testing.EdaServiceTest;
import java.util.Arrays;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;
import org.springframework.kafka.listener.ConcurrentMessageListenerContainer;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

/**
 * The production wiring of notification-svc: consumer containers on the declared topics and the
 * group's retry topics, the handler registry, DLQ endpoints, the polling relay and the jobs.
 * Containers are built but not started (no broker here).
 */
@EdaServiceTest
@TestPropertySource(
    properties = {
      "eda.consumer.enabled=true",
      "eda.consumer.auto-startup=false",
      "eda.outbox-relay=polling",
      "eda.jobs.enabled=true",
      "eda.housekeeping.enabled=true"
    })
class RuntimeWiringIT {
  @Autowired ApplicationContext ctx;
  @Autowired MockMvc mvc;

  @Test
  void theRuntimeIsWiredFromConfiguration() throws Exception {
    HandlerRegistry registry = ctx.getBean(HandlerRegistry.class);
    assertThat(registry.types())
        .containsExactlyInAnyOrder(
            "com.edacommerce.order.OrderPlaced",
            "com.edacommerce.order.OrderConfirmed",
            "com.edacommerce.order.OrderCancelled",
            "com.edacommerce.order.OrderShipped",
            "com.edacommerce.order.InvoiceIssued",
            "com.edacommerce.order.OrderDelivered",
            "com.edacommerce.shipping.ShipmentCreated",
            "com.edacommerce.shipping.ShipmentException",
            "com.edacommerce.returns.ReturnAuthorized",
            "com.edacommerce.returns.ReturnRejected",
            "com.edacommerce.returns.ReturnRefunded",
            "com.edacommerce.returns.ReturnClosed");
    @SuppressWarnings("unchecked")
    ConcurrentMessageListenerContainer<String, byte[]> main =
        ctx.getBean("edaMainContainer", ConcurrentMessageListenerContainer.class);
    @SuppressWarnings("unchecked")
    ConcurrentMessageListenerContainer<String, byte[]> retry =
        ctx.getBean("edaRetryContainer", ConcurrentMessageListenerContainer.class);
    assertThat(main.getContainerProperties().getTopics())
        .containsExactly(
            "order.events.v1", "payment.events.v1", "shipping.events.v1", "returns.events.v1");
    assertThat(main.getContainerProperties().getGroupId()).isEqualTo("notification-svc");
    assertThat(Arrays.asList(retry.getContainerProperties().getTopics()))
        .containsExactly(
            "notification-svc.retry.10s",
            "notification-svc.retry.1m",
            "notification-svc.retry.10m");
    assertThat(retry.getContainerProperties().getGroupId()).isEqualTo("notification-svc-retry");
    assertThat(ctx.getBeansOfType(DlqController.class)).hasSize(1);
    assertThat(ctx.getBeansOfType(PeriodicJob.class).values())
        .extracting(PeriodicJob::name)
        .contains("outbox-relay", "housekeeping", "contact-retention");
    mvc.perform(get("/health/live")).andExpect(status().isOk());
    mvc.perform(get("/health/ready"))
        .andExpect(status().isServiceUnavailable())
        .andExpect(jsonPath("$.checks.database").value("UP"));
  }
}
