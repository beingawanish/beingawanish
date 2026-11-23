package com.edacommerce.checkout.config;

import com.edacommerce.checkout.adapters.in.messaging.CatalogViewHandlers;
import com.edacommerce.checkout.adapters.out.persistence.JdbcCheckoutPersistence;
import com.edacommerce.checkout.application.CheckoutUseCases;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import java.time.Clock;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Composition root of checkout-svc. */
@Configuration(proxyBeanMethods = false)
public class CheckoutConfiguration {
  @Bean
  CheckoutUseCases checkoutUseCases(
      JdbcCheckoutPersistence persistence, OutboxWriter outbox, IdGenerator ids, Clock clock) {
    return new CheckoutUseCases(persistence, persistence, persistence, outbox, ids, clock);
  }

  @Bean
  CatalogViewHandlers catalogViewHandlers(
      JdbcCheckoutPersistence persistence, CheckoutUseCases useCases) {
    return new CatalogViewHandlers(persistence, useCases);
  }
}
