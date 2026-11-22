package com.edacommerce.payment.application;

import com.edacommerce.kernel.Money;
import com.edacommerce.payment.domain.Payment;

/**
 * Port to the payment service provider (anti-corruption layer). The fake PSP and a real one implement
 * it; the domain never sees PSP status codes. Our paymentId / refundId is always the PSP idempotency
 * key (merchant reference). Unavailability is reported as a Transient exception by the adapter.
 */
public interface PaymentGateway {
  Payment.AuthorizeResult authorize(String merchantReference, Money amount, String paymentMethodToken);

  /** Asynchronous: the outcome arrives as a capture.* notification. */
  void capture(String merchantReference, String pspReference, Money amount);

  /** Synchronous and safe even when the PSP never saw the reference. */
  void voidAuthorization(String merchantReference);

  /** Asynchronous: the outcome arrives as a refund.* notification. */
  void refund(String refundId, String paymentReference, Money amount);

  Payment.PspStatus status(String merchantReference);
}
