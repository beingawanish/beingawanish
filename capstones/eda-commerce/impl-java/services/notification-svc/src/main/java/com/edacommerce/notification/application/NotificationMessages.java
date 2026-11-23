package com.edacommerce.notification.application;

import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.notification.Channel;
import com.edacommerce.notification.NotificationSent;

/** NotificationSent on notification.events.v1, keyed by orderId (customerId without an order). */
public final class NotificationMessages {
  private NotificationMessages() {}

  public static final String EVENTS = "notification.events.v1";

  public static OutgoingMessage sent(NotificationRepository.Sent s) {
    NotificationSent e =
        NotificationSent.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setNotificationId(s.notificationId())
            .setOrderId(s.orderId())
            .setCustomerId(s.customerId())
            .setChannel(Channel.valueOf(s.channel()))
            .setTemplate(s.template())
            .setSourceEventId(s.sourceEventId())
            .setAttachmentCount(s.attachmentCount())
            .setSentAt(s.sentAt())
            .build();
    String key = s.orderId() != null ? s.orderId() : s.customerId();
    return OutgoingMessage.of(EVENTS, key, e, "Notification", s.notificationId(), 1);
  }
}
