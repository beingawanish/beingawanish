package com.edacommerce.edacommon.config;

import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.core.Ordered;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.env.StandardEnvironment;

/**
 * Maps the environment variables of guide §7 onto Spring properties, in one place, so every service
 * reads exactly the same names. Two property sources are added:
 *
 * <ul>
 *   <li>{@code edaEnvironment}: only variables that are set, ranked just below the OS environment
 *       (above application.yml), so a variable always wins over a service default.
 *   <li>{@code edaDefaults}: the documented defaults, ranked last, derived from the service name
 *       (database {@code <context>_db}, role {@code <context>_svc}).
 * </ul>
 */
public class EdaEnvironmentPostProcessor implements EnvironmentPostProcessor, Ordered {

  @Override
  public int getOrder() {
    // After ConfigDataEnvironmentPostProcessor, so application.yml (eda.service-name) is visible.
    return Ordered.LOWEST_PRECEDENCE;
  }

  @Override
  public void postProcessEnvironment(ConfigurableEnvironment env, SpringApplication application) {
    Map<String, Object> fromEnv = new LinkedHashMap<>();
    map(env, fromEnv, "SERVICE_NAME", "eda.service-name", "spring.application.name");
    map(env, fromEnv, "ENVIRONMENT", "eda.environment");
    map(env, fromEnv, "HTTP_PORT", "server.port");
    map(env, fromEnv, "CONSUMER_GROUP", "eda.consumer-group");
    map(env, fromEnv, "KAFKA_BOOTSTRAP_SERVERS", "eda.kafka.bootstrap-servers");
    map(env, fromEnv, "KAFKA_SECURITY_PROTOCOL", "eda.kafka.security-protocol");
    map(env, fromEnv, "KAFKA_SSL_CA_LOCATION", "eda.kafka.ssl-ca-location");
    map(env, fromEnv, "KAFKA_SSL_CERT_LOCATION", "eda.kafka.ssl-cert-location");
    map(env, fromEnv, "KAFKA_SSL_KEY_LOCATION", "eda.kafka.ssl-key-location");
    map(env, fromEnv, "POD_NAME", "eda.kafka.group-instance-id");
    map(env, fromEnv, "SCHEMA_REGISTRY_URL", "eda.schema-registry-url");
    map(env, fromEnv, "DB_USER", "spring.datasource.username");
    map(env, fromEnv, "DB_PASSWORD", "spring.datasource.password");
    map(env, fromEnv, "DB_POOL_SIZE", "spring.datasource.hikari.maximum-pool-size");
    map(env, fromEnv, "OUTBOX_RELAY", "eda.outbox-relay");
    map(env, fromEnv, "OUTBOX_POLL_INTERVAL", "eda.outbox-poll-interval");
    map(env, fromEnv, "S3_ENDPOINT", "eda.s3.endpoint");
    map(env, fromEnv, "S3_REGION", "eda.s3.region");
    map(env, fromEnv, "S3_ACCESS_KEY", "eda.s3.access-key");
    map(env, fromEnv, "S3_SECRET_KEY", "eda.s3.secret-key");
    map(env, fromEnv, "AUTH_MODE", "eda.auth.mode");
    map(env, fromEnv, "OIDC_ISSUER_URL", "eda.auth.issuer-url");
    map(env, fromEnv, "OIDC_AUDIENCE", "eda.auth.audience");
    map(env, fromEnv, "LOG_LEVEL", "logging.level.root");
    map(env, fromEnv, "LOG_FORMAT", "eda.log-format");
    if ("plain".equalsIgnoreCase(env.getProperty("LOG_FORMAT"))) {
      env.addActiveProfile("log-plain");
    }
    if (env.getProperty("DB_HOST") != null
        || env.getProperty("DB_PORT") != null
        || env.getProperty("DB_NAME") != null) {
      fromEnv.put("spring.datasource.url", jdbcUrl(env));
    }
    if (!fromEnv.isEmpty()) {
      env.getPropertySources()
          .addAfter(
              StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME,
              new MapPropertySource("edaEnvironment", fromEnv));
    }

    String service = env.getProperty("SERVICE_NAME", env.getProperty("eda.service-name", "app"));
    // eda.db-context lets two processes of one codebase share a database (order-svc and its
    // projector).
    String context = env.getProperty("eda.db-context", contextOf(service));
    Map<String, Object> defaults = new LinkedHashMap<>();
    defaults.put("spring.application.name", service);
    defaults.put("spring.datasource.url", jdbcUrl(env));
    defaults.put("spring.datasource.username", context + "_svc");
    defaults.put("spring.datasource.password", context + "_svc");
    defaults.put("spring.datasource.hikari.maximum-pool-size", "10");
    // Guide §6.5: 2 s pool acquisition, so a stalled database answers 503 fast.
    defaults.put("spring.datasource.hikari.connection-timeout", "2000");
    defaults.put("spring.jpa.open-in-view", "false");
    defaults.put("spring.threads.virtual.enabled", "true");
    defaults.put("spring.jackson.serialization.write-dates-as-timestamps", "false");
    defaults.put("spring.jackson.default-property-inclusion", "always");
    defaults.put("server.shutdown", "graceful");
    defaults.put("spring.lifecycle.timeout-per-shutdown-phase", "30s");
    defaults.put("management.endpoints.web.exposure.include", "health");
    // The consumer runtime creates its own spans and must forward records with their headers
    // untouched (ADR-0007), so the generic Kafka instrumentation stays off.
    defaults.put("otel.instrumentation.kafka.enabled", "false");
    defaults.put("otel.resource.attributes", "service.namespace=edacommerce,eda.impl=java");
    defaults.put("eda.log-format", "json");
    // edacommon builds its own Kafka clients (KafkaClients) from the §7 variables.
    defaults.put(
        "spring.autoconfigure.exclude",
        "org.springframework.boot.autoconfigure.kafka.KafkaAutoConfiguration");
    env.getPropertySources().addLast(new MapPropertySource("edaDefaults", defaults));
  }

  static String contextOf(String serviceName) {
    String s =
        serviceName.endsWith("-svc")
            ? serviceName.substring(0, serviceName.length() - 4)
            : serviceName;
    return s.replace('-', '_');
  }

  private static String jdbcUrl(ConfigurableEnvironment env) {
    String service = env.getProperty("SERVICE_NAME", env.getProperty("eda.service-name", "app"));
    String host = env.getProperty("DB_HOST", "localhost");
    String port = env.getProperty("DB_PORT", "5432");
    String name =
        env.getProperty("DB_NAME", env.getProperty("eda.db-context", contextOf(service)) + "_db");
    return "jdbc:postgresql://" + host + ":" + port + "/" + name;
  }

  private static void map(
      ConfigurableEnvironment env, Map<String, Object> target, String variable, String... keys) {
    String value = env.getProperty(variable);
    if (value != null && !value.isBlank()) {
      for (String key : keys) {
        target.put(key, value);
      }
    }
  }
}
