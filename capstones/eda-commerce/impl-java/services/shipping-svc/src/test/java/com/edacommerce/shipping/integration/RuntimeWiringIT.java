package com.edacommerce.shipping.integration;

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
 * The production wiring of shipping-svc: consumer containers on the declared topics and the group's
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
            "com.edacommerce.fulfilment.OrderPacked", "com.edacommerce.shipping.IssueReturnLabel");
    @SuppressWarnings("unchecked")
    ConcurrentMessageListenerContainer<String, byte[]> main =
        ctx.getBean("edaMainContainer", ConcurrentMessageListenerContainer.class);
    @SuppressWarnings("unchecked")
    ConcurrentMessageListenerContainer<String, byte[]> retry =
        ctx.getBean("edaRetryContainer", ConcurrentMessageListenerContainer.class);
    assertThat(main.getContainerProperties().getTopics())
        .containsExactly("fulfilment.events.v1", "shipping.commands.v1");
    assertThat(main.getContainerProperties().getGroupId()).isEqualTo("shipping-svc");
    assertThat(Arrays.asList(retry.getContainerProperties().getTopics()))
        .containsExactly(
            "shipping-svc.retry.10s", "shipping-svc.retry.1m", "shipping-svc.retry.10m");
    assertThat(retry.getContainerProperties().getGroupId()).isEqualTo("shipping-svc-retry");
    assertThat(ctx.getBeansOfType(DlqController.class)).hasSize(1);
    assertThat(ctx.getBeansOfType(PeriodicJob.class).values())
        .extracting(PeriodicJob::name)
        .contains(
            "outbox-relay", "housekeeping", "carrier-tracking", "booking-retries", "fake-carrier");
    mvc.perform(get("/health/live")).andExpect(status().isOk());
    mvc.perform(get("/health/ready"))
        .andExpect(status().isServiceUnavailable())
        .andExpect(jsonPath("$.checks.database").value("UP"));
  }
}
