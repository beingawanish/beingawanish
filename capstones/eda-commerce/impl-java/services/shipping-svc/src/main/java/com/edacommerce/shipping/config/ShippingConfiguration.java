package com.edacommerce.shipping.config;

import com.edacommerce.edacommon.claimcheck.ClaimCheckStore;
import com.edacommerce.edacommon.consumer.MessageHandlerGroup;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.inbox.Inbox;
import com.edacommerce.edacommon.jobs.PeriodicJob;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.edacommon.webhooks.WebhookReceiver;
import com.edacommerce.edacommon.webhooks.WebhookVerifier;
import com.edacommerce.shipping.adapters.in.messaging.ShippingHandlers;
import com.edacommerce.shipping.adapters.out.carrier.fake.CarrierWebhookTransport;
import com.edacommerce.shipping.adapters.out.carrier.fake.FakeCarrier;
import com.edacommerce.shipping.adapters.out.carrier.fake.FakeCarrierConfig;
import com.edacommerce.shipping.adapters.out.carrier.fake.HttpCarrierWebhookTransport;
import com.edacommerce.shipping.adapters.out.documents.OpenPdfLabelRenderer;
import com.edacommerce.shipping.application.LabelRenderer;
import com.edacommerce.shipping.application.ShipmentRepository;
import com.edacommerce.shipping.application.ShippingUseCases;
import com.edacommerce.shipping.application.TrackingEvents;
import java.time.Clock;
import java.time.Duration;
import java.util.Random;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.transaction.support.TransactionTemplate;

/** Composition root of shipping-svc. */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(ShippingConfiguration.ShippingProperties.class)
public class ShippingConfiguration {

  /** CARRIER_WEBHOOK_SECRET, CARRIER_WEBHOOK_URL, FAKE_CARRIER_* and job intervals. */
  @ConfigurationProperties(prefix = "shipping")
  public record ShippingProperties(
      CarrierProperties carrier,
      Duration bookingRetryInterval,
      Duration trackingInterval,
      Duration carrierTickInterval,
      FakeCarrierConfig fakeCarrier) {
    public ShippingProperties {
      carrier =
          carrier == null
              ? new CarrierProperties(
                  "dev-carrier-secret", "http://localhost:8107/webhooks/carrier")
              : carrier;
      bookingRetryInterval =
          bookingRetryInterval == null ? Duration.ofSeconds(5) : bookingRetryInterval;
      trackingInterval = trackingInterval == null ? Duration.ofSeconds(1) : trackingInterval;
      carrierTickInterval =
          carrierTickInterval == null ? Duration.ofMillis(500) : carrierTickInterval;
      fakeCarrier =
          FakeCarrierConfig.DEFAULTS.merge(
              fakeCarrier == null ? FakeCarrierConfig.DEFAULTS : fakeCarrier);
    }
  }

  /** The carrier's webhook settings. */
  public record CarrierProperties(String webhookSecret, String webhookUrl) {}

  @Bean
  WebhookVerifier carrierWebhookVerifier(ShippingProperties p, Clock clock) {
    return new WebhookVerifier(p.carrier().webhookSecret(), clock);
  }

  @Bean
  WebhookReceiver carrierWebhookReceiver(
      WebhookVerifier verifier, Inbox inbox, TransactionTemplate tx, EdaMetrics metrics) {
    return new WebhookReceiver("carrier", verifier, inbox, tx, metrics);
  }

  @Bean
  @ConditionalOnMissingBean
  CarrierWebhookTransport carrierWebhookTransport(ShippingProperties p) {
    return new HttpCarrierWebhookTransport(p.carrier().webhookUrl(), 8);
  }

  @Bean
  FakeCarrier fakeCarrier(
      ShippingProperties p,
      CarrierWebhookTransport transport,
      WebhookVerifier verifier,
      Clock clock,
      IdGenerator ids) {
    return new FakeCarrier(p.fakeCarrier(), transport, verifier, clock, ids, new Random());
  }

  @Bean
  LabelRenderer labelRenderer() {
    return new OpenPdfLabelRenderer();
  }

  @Bean
  ShippingUseCases shippingUseCases(
      ShipmentRepository shipments,
      TrackingEvents tracking,
      FakeCarrier carrier,
      LabelRenderer labels,
      ClaimCheckStore documents,
      OutboxWriter outbox,
      TransactionTemplate tx,
      IdGenerator ids,
      Clock clock) {
    return new ShippingUseCases(
        shipments, tracking, carrier, labels, documents, outbox, tx, ids, clock);
  }

  @Bean
  MessageHandlerGroup shippingHandlers(ShippingUseCases useCases) {
    return () -> ShippingHandlers.all(useCases);
  }

  /** Applies stored webhooks right after the endpoint answered; the job is the safety net. */
  @Bean(destroyMethod = "shutdown")
  ExecutorService trackingExecutor() {
    return Executors.newSingleThreadExecutor(Thread.ofVirtual().name("carrier-tracking").factory());
  }

  @Bean
  Runnable trackingKick(
      ExecutorService trackingExecutor, ShippingUseCases useCases, Environment env) {
    boolean enabled = env.getProperty("eda.jobs.enabled", Boolean.class, true);
    return () -> {
      if (enabled) {
        trackingExecutor.execute(() -> useCases.processTracking(50));
      }
    };
  }

  @Bean
  @ConditionalOnProperty(name = "eda.jobs.enabled", havingValue = "true", matchIfMissing = true)
  PeriodicJob trackingJob(ShippingUseCases useCases, ShippingProperties p) {
    return new PeriodicJob(
        "carrier-tracking", p.trackingInterval(), () -> useCases.processTracking(100));
  }

  @Bean
  @ConditionalOnProperty(name = "eda.jobs.enabled", havingValue = "true", matchIfMissing = true)
  PeriodicJob bookingRetryJob(ShippingUseCases useCases, ShippingProperties p) {
    return new PeriodicJob(
        "booking-retries", p.bookingRetryInterval(), () -> useCases.retryDueBookings(50));
  }

  @Bean
  @ConditionalOnProperty(name = "eda.jobs.enabled", havingValue = "true", matchIfMissing = true)
  PeriodicJob fakeCarrierJob(FakeCarrier carrier, ShippingProperties p) {
    return new PeriodicJob("fake-carrier", p.carrierTickInterval(), carrier::tick);
  }
}
