package com.edacommerce.returns.integration;

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
 * The production wiring of returns-svc: consumer containers on the declared topics and the group's
 * retry topics, the handler registry, DLQ endpoints, the polling relay and the jobs. Containers are
 * built but not started (no broker here).
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
            "com.edacommerce.order.OrderDelivered",
            "com.edacommerce.order.OrderCancelled",
            "com.edacommerce.fulfilment.FulfilmentAccepted",
            "com.edacommerce.shipping.ShipmentCreated",
            "com.edacommerce.fulfilment.ReturnReceived",
            "com.edacommerce.fulfilment.ReturnInspected",
            "com.edacommerce.inventory.ItemsRestocked",
            "com.edacommerce.payment.RefundSucceeded",
            "com.edacommerce.payment.RefundFailed");
    @SuppressWarnings("unchecked")
    ConcurrentMessageListenerContainer<String, byte[]> main =
        ctx.getBean("edaMainContainer", ConcurrentMessageListenerContainer.class);
    @SuppressWarnings("unchecked")
    ConcurrentMessageListenerContainer<String, byte[]> retry =
        ctx.getBean("edaRetryContainer", ConcurrentMessageListenerContainer.class);
    assertThat(main.getContainerProperties().getTopics())
        .containsExactly(
            "order.events.v1",
            "payment.events.v1",
            "inventory.events.v1",
            "fulfilment.events.v1",
            "shipping.events.v1");
    assertThat(main.getContainerProperties().getGroupId()).isEqualTo("returns-svc");
    assertThat(Arrays.asList(retry.getContainerProperties().getTopics()))
        .containsExactly("returns-svc.retry.10s", "returns-svc.retry.1m", "returns-svc.retry.10m");
    assertThat(retry.getContainerProperties().getGroupId()).isEqualTo("returns-svc-retry");
    assertThat(ctx.getBeansOfType(DlqController.class)).hasSize(1);
    assertThat(ctx.getBeansOfType(PeriodicJob.class).values())
        .extracting(PeriodicJob::name)
        .contains("outbox-relay", "housekeeping", "returns-deadline-sweeper");
    mvc.perform(get("/health/live")).andExpect(status().isOk());
    mvc.perform(get("/health/ready"))
        .andExpect(status().isServiceUnavailable())
        .andExpect(jsonPath("$.checks.database").value("UP"));
  }
}
