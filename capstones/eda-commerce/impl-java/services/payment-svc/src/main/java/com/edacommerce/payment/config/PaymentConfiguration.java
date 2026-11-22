package com.edacommerce.payment.config;

import com.edacommerce.edacommon.inbox.Inbox;
import com.edacommerce.edacommon.jobs.PeriodicJob;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.edacommon.webhooks.WebhookReceiver;
import com.edacommerce.edacommon.webhooks.WebhookVerifier;
import com.edacommerce.payment.adapters.in.messaging.PaymentCommandHandlers;
import com.edacommerce.payment.adapters.out.psp.fake.FakePsp;
import com.edacommerce.payment.adapters.out.psp.fake.FakePspConfig;
import com.edacommerce.payment.adapters.out.psp.fake.HttpPspWebhookTransport;
import com.edacommerce.payment.adapters.out.psp.fake.PspWebhookTransport;
import com.edacommerce.payment.application.PaymentRepository;
import com.edacommerce.payment.application.PaymentUseCases;
import com.edacommerce.payment.application.PspNotifications;
import com.edacommerce.payment.application.RefundRepository;
import com.edacommerce.payment.domain.Payment;
import java.time.Clock;
import java.time.Duration;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.transaction.support.TransactionTemplate;

/** Composition root of payment-svc. */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties({PaymentConfiguration.PspProperties.class, PaymentConfiguration.FakePspProperties.class})
public class PaymentConfiguration {

  /** PSP_WEBHOOK_SECRET, PSP_WEBHOOK_URL and client settings. */
  @ConfigurationProperties(prefix = "payment.psp")
  public record PspProperties(String webhookSecret, String webhookUrl, Duration requestTimeout,
      Duration reconcileInterval, Duration reconcileWindow, Duration pendingCheckAfter) {}

  /** FAKE_PSP_* (admin.yaml FakePspConfig, upper snake case). */
  @ConfigurationProperties(prefix = "payment.fake-psp")
  public record FakePspProperties(Double declineRate, Double timeoutRate, Double duplicateWebhookRate,
      Integer webhookDelayMs, Integer slowWebhookMs, Integer apiLatencyMs) {
    FakePspConfig toConfig() {
      return FakePspConfig.DEFAULTS.merge(new FakePspConfig(declineRate, timeoutRate, duplicateWebhookRate, webhookDelayMs, slowWebhookMs, apiLatencyMs));
    }
  }

  @Bean
  WebhookVerifier pspWebhookVerifier(PspProperties p, Clock clock) {
    return new WebhookVerifier(p.webhookSecret(), clock);
  }

  @Bean
  @ConditionalOnMissingBean
  PspWebhookTransport pspWebhookTransport(PspProperties p) {
    return new HttpPspWebhookTransport(p.webhookUrl(), 8);
  }

  @Bean(destroyMethod = "shutdown")
  FakePsp fakePsp(FakePspProperties fake, PspWebhookTransport transport, WebhookVerifier verifier, Clock clock, PspProperties p) {
    return new FakePsp(fake.toConfig(), transport, verifier, clock, p.requestTimeout());
  }

  @Bean
  PaymentUseCases paymentUseCases(PaymentRepository payments, RefundRepository refunds, FakePsp psp,
      PspNotifications notifications, OutboxWriter outbox, Clock clock, PspProperties p) {
    return new PaymentUseCases(payments, refunds, psp, notifications, outbox, clock,
        new Payment.ReconciliationPolicy(p.reconcileInterval(), p.reconcileWindow(), p.pendingCheckAfter()));
  }

  @Bean
  WebhookReceiver pspWebhookReceiver(WebhookVerifier verifier, Inbox inbox, TransactionTemplate tx, EdaMetrics metrics) {
    return new WebhookReceiver("psp", verifier, inbox, tx, metrics);
  }

  /** Applies stored webhooks right after the endpoint answered; the periodic job is the safety net. */
  @Bean(destroyMethod = "shutdown")
  ExecutorService pspNotificationExecutor() {
    return Executors.newSingleThreadExecutor(Thread.ofVirtual().name("psp-notifications").factory());
  }

  @Bean
  Runnable pspNotificationKick(ExecutorService pspNotificationExecutor, PaymentUseCases useCases,
      org.springframework.core.env.Environment env) {
    boolean enabled = env.getProperty("eda.jobs.enabled", Boolean.class, true);
    return () -> {
      if (enabled) {
        pspNotificationExecutor.execute(() -> useCases.processNotifications(50));
      }
    };
  }

  @Bean
  @ConditionalOnProperty(name = "eda.jobs.enabled", havingValue = "true", matchIfMissing = true)
  PeriodicJob pspNotificationJob(PaymentUseCases useCases) {
    return new PeriodicJob("psp-notifications", Duration.ofSeconds(1), () -> useCases.processNotifications(50));
  }

  @Bean
  @ConditionalOnProperty(name = "eda.jobs.enabled", havingValue = "true", matchIfMissing = true)
  PeriodicJob reconciliationJob(PaymentUseCases useCases) {
    return new PeriodicJob("psp-reconciliation", Duration.ofSeconds(5), () -> useCases.reconcileDue(50));
  }

  @Bean
  PaymentCommandHandlers.Authorize authorizePaymentHandler(PaymentUseCases u) {
    return new PaymentCommandHandlers.Authorize(u);
  }

  @Bean
  PaymentCommandHandlers.Capture capturePaymentHandler(PaymentUseCases u) {
    return new PaymentCommandHandlers.Capture(u);
  }

  @Bean
  PaymentCommandHandlers.VoidCmd voidPaymentHandler(PaymentUseCases u) {
    return new PaymentCommandHandlers.VoidCmd(u);
  }

  @Bean
  PaymentCommandHandlers.RefundCmd refundPaymentHandler(PaymentUseCases u) {
    return new PaymentCommandHandlers.RefundCmd(u);
  }
}
