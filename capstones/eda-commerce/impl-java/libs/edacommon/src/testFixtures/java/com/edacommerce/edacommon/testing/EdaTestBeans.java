package com.edacommerce.edacommon.testing;

import com.edacommerce.edacommon.claimcheck.ClaimCheckStore;
import com.edacommerce.edacommon.serde.SchemaRegistryClient;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;

/** In-process replacements for the registry, object storage and the clock in service tests. */
@TestConfiguration(proxyBeanMethods = false)
public class EdaTestBeans {
  @Bean
  @Primary
  SchemaRegistryClient testSchemaRegistry() {
    return new InMemorySchemaRegistry();
  }

  @Bean
  @Primary
  ClaimCheckStore testClaimCheckStore() {
    return new InMemoryClaimCheckStore();
  }

  @Bean
  @Primary
  MutableClock testClock() {
    return new MutableClock();
  }
}
