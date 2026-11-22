package com.edacommerce.edacommon.testing;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.ContextConfiguration;

/**
 * A service integration test: the real Spring context and Flyway migrations on a fresh PostgreSQL,
 * with the Kafka listener containers and background jobs off (tests drive handlers through
 * {@link MessageDriver} and call jobs directly), an in-memory registry and claim-check store, and a
 * {@link MutableClock}. Skipped when no PostgreSQL is available.
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@RequiresPostgres
@SpringBootTest(
    properties = {
      "eda.consumer.enabled=false",
      "eda.jobs.enabled=false",
      "eda.housekeeping.enabled=false",
      "eda.outbox-relay=debezium",
      "otel.sdk.disabled=true",
      "eda.log-format=plain",
      "spring.main.allow-bean-definition-overriding=true"
    })
@AutoConfigureMockMvc
@ContextConfiguration(initializers = TestDatabaseInitializer.class)
@Import(EdaTestBeans.class)
public @interface EdaServiceTest {}
