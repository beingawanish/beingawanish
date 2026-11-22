package com.edacommerce.notification.config;

import com.edacommerce.edacommon.claimcheck.ClaimCheckStore;
import com.edacommerce.edacommon.consumer.MessageHandlerGroup;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.jobs.PeriodicJob;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.notification.adapters.in.messaging.NotificationHandlers;
import com.edacommerce.notification.adapters.out.mail.fake.FakeMailGateway;
import com.edacommerce.notification.application.ContactRepository;
import com.edacommerce.notification.application.NotificationRepository;
import com.edacommerce.notification.application.NotificationUseCases;
import java.time.Clock;
import java.time.Duration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Composition root of notification-svc. */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(NotificationConfiguration.NotificationProperties.class)
public class NotificationConfiguration {

  /** Contact retention (ADR-0013) and its sweep interval. */
  @ConfigurationProperties(prefix = "notification")
  public record NotificationProperties(Duration contactRetention, Duration retentionSweepInterval) {
    public NotificationProperties {
      contactRetention = contactRetention == null ? Duration.ofDays(400) : contactRetention;
      retentionSweepInterval =
          retentionSweepInterval == null ? Duration.ofHours(1) : retentionSweepInterval;
    }
  }

  @Bean
  FakeMailGateway fakeMailGateway() {
    return new FakeMailGateway();
  }

  @Bean
  NotificationUseCases notificationUseCases(
      ContactRepository contacts,
      NotificationRepository notifications,
      FakeMailGateway mail,
      ClaimCheckStore documents,
      OutboxWriter outbox,
      IdGenerator ids,
      Clock clock,
      NotificationProperties p) {
    return new NotificationUseCases(
        contacts, notifications, mail, documents, outbox, ids, clock, p.contactRetention());
  }

  @Bean
  MessageHandlerGroup notificationHandlers(NotificationUseCases useCases) {
    return () -> NotificationHandlers.all(useCases);
  }

  @Bean
  @ConditionalOnProperty(name = "eda.jobs.enabled", havingValue = "true", matchIfMissing = true)
  PeriodicJob contactRetentionJob(NotificationUseCases useCases, NotificationProperties p) {
    return new PeriodicJob(
        "contact-retention", p.retentionSweepInterval(), useCases::forgetExpiredContacts);
  }
}
