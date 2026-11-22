package com.edacommerce.catalog.config;

import com.edacommerce.catalog.adapters.in.messaging.StockLevelHandler;
import com.edacommerce.catalog.application.CatalogUseCases;
import com.edacommerce.catalog.application.ProductRepository;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import java.time.Clock;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Composition root of catalog-svc. */
@Configuration(proxyBeanMethods = false)
public class CatalogConfiguration {
  @Bean
  CatalogUseCases catalogUseCases(
      ProductRepository products, OutboxWriter outbox, Clock clock, IdGenerator ids) {
    return new CatalogUseCases(products, outbox, clock, ids);
  }

  @Bean
  StockLevelHandler stockLevelHandler(CatalogUseCases useCases) {
    return new StockLevelHandler(useCases);
  }
}
