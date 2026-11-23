package com.edacommerce.edacommon.testing;

import java.util.Map;
import org.springframework.context.ApplicationContextInitializer;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.MapPropertySource;

/** Points a Spring test context at a fresh database (one per cached context). */
public class TestDatabaseInitializer
    implements ApplicationContextInitializer<ConfigurableApplicationContext> {
  @Override
  public void initialize(ConfigurableApplicationContext context) {
    TestDatabases.TestDb db = TestDatabases.fresh();
    context
        .getEnvironment()
        .getPropertySources()
        .addFirst(
            new MapPropertySource(
                "edaTestDatabase",
                Map.of(
                    "spring.datasource.url", db.url(),
                    "spring.datasource.username", db.user(),
                    "spring.datasource.password", db.password())));
  }
}
