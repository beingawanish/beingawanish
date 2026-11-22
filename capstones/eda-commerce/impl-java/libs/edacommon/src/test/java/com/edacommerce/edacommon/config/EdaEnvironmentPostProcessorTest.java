package com.edacommerce.edacommon.config;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.env.StandardEnvironment;

class EdaEnvironmentPostProcessorTest {
  @Test
  void mapsTheEnvironmentContractAndDerivesDefaults() {
    StandardEnvironment env = new StandardEnvironment();
    env.getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
    env.getPropertySources()
        .addFirst(
            new MapPropertySource(
                StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME,
                Map.of("SERVICE_NAME", "payment-svc", "HTTP_PORT", "8080", "DB_HOST", "postgres",
                    "OUTBOX_RELAY", "polling", "POD_NAME", "payment-svc-7d9")));
    new EdaEnvironmentPostProcessor().postProcessEnvironment(env, new SpringApplication());

    assertThat(env.getProperty("eda.service-name")).isEqualTo("payment-svc");
    assertThat(env.getProperty("server.port")).isEqualTo("8080");
    assertThat(env.getProperty("spring.datasource.url")).isEqualTo("jdbc:postgresql://postgres:5432/payment_db");
    assertThat(env.getProperty("spring.datasource.username")).isEqualTo("payment_svc");
    assertThat(env.getProperty("eda.outbox-relay")).isEqualTo("polling");
    assertThat(env.getProperty("eda.kafka.group-instance-id")).isEqualTo("payment-svc-7d9");
    assertThat(env.getProperty("spring.datasource.hikari.connection-timeout")).isEqualTo("2000");
    assertThat(EdaEnvironmentPostProcessor.contextOf("order-history-projector")).isEqualTo("order_history_projector");
  }
}
