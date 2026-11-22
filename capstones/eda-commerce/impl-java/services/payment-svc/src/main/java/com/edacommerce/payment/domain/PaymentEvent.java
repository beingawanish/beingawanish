package com.edacommerce.payment.domain;

import com.edacommerce.kernel.Money;
import java.time.Instant;

/** Facts payment-svc publishes on payment.events.v1. */
public sealed interface PaymentEvent {
  record Authorized(String pspReference, Money amount, Instant authorizedAt, Instant expiresAt) implements PaymentEvent {}

  record Declined(DeclineCode reason, String pspReference, Instant declinedAt) implements PaymentEvent {}

  record Captured(Money amount, String pspReference, Instant capturedAt) implements PaymentEvent {}

  record CaptureFailed(boolean authorizationExpired, boolean retryable, Instant failedAt) implements PaymentEvent {}

  record Voided(Instant voidedAt) implements PaymentEvent {}
}
