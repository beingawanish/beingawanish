package com.edacommerce.payment.domain;

import com.edacommerce.kernel.Money;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * The payment aggregate. Idempotent on paymentId (the saga reuses it on every resend, and it is the
 * PSP idempotency key, ADR-0006). Pure: PSP results and time are passed in; the application makes the
 * PSP calls the decisions ask for.
 */
public record Payment(
    String paymentId,
    String orderId,
    String customerId,
    Money amount,
    String paymentMethodToken,
    PaymentStatus status,
    String pspReference,
    DeclineCode declineReason,
    Instant authorizedAt,
    Instant authorizationExpiresAt,
    boolean captureFailureAuthExpired,
    boolean captureFailureRetryable,
    Instant changedAt,
    Instant reconcileDeadline,
    Instant nextReconcileAt,
    boolean lateSuccessVoided,
    long version) {

  /** Authorisations are valid for about 7 days (ADR-0015). */
  public static final Duration AUTHORIZATION_VALIDITY = Duration.ofDays(7);

  /** Reconciliation policy for unknown outcomes (architecture §5.6). */
  public record ReconciliationPolicy(Duration interval, Duration window, Duration pendingCheckAfter) {
    public static final ReconciliationPolicy DEFAULT =
        new ReconciliationPolicy(Duration.ofSeconds(15), Duration.ofMinutes(2), Duration.ofMinutes(5));
  }

  /** What the PSP said to an authorisation request. */
  public sealed interface AuthorizeResult {
    record Accepted(String pspReference) implements AuthorizeResult {}

    record Declined(DeclineCode code) implements AuthorizeResult {}

    /** No answer within the client timeout: we do not know. */
    record Timeout() implements AuthorizeResult {}
  }

  /** What a status query (reconciliation) found at the PSP. */
  public sealed interface PspStatus {
    record Authorized(String pspReference) implements PspStatus {}

    record Declined(DeclineCode code) implements PspStatus {}

    record Pending() implements PspStatus {}

    record NotFound() implements PspStatus {}
  }

  /** A normalised PSP notification (the webhook adapter maps the PSP's vocabulary to this). */
  public sealed interface Notification {
    record AuthorizationSucceeded(String pspReference) implements Notification {}

    record AuthorizationFailed(DeclineCode code) implements Notification {}

    record CaptureSucceeded(String pspReference) implements Notification {}

    record CaptureFailed(boolean authorizationExpired) implements Notification {}
  }

  /** New state, events to publish, PSP calls to make. {@code notYet}: retry the command later. */
  public record Decision(Payment payment, List<PaymentEvent> events, List<PspAction> actions, boolean changed, boolean notYet) {
    static Decision of(Payment p, List<PaymentEvent> events, List<PspAction> actions) {
      return new Decision(p, events, actions, true, false);
    }

    static Decision replay(Payment p, List<PaymentEvent> events) {
      return new Decision(p, events, List.of(), false, false);
    }

    static Decision nothing(Payment p) {
      return new Decision(p, List.of(), List.of(), false, false);
    }
  }

  public static Payment requested(
      String paymentId, String orderId, String customerId, Money amount, String token, Instant now) {
    return new Payment(paymentId, orderId, customerId, amount, token, PaymentStatus.PENDING, null, null, null, null,
        false, false, now, null, null, false, 1);
  }

  /** A VoidPayment for a payment we never saw: remember it so a late AuthorizePayment is not executed. */
  public static Decision voidUnknown(String paymentId, String orderId, Money amount, Instant now) {
    Payment p = new Payment(paymentId, orderId, "", amount, "", PaymentStatus.VOIDED, null, null, null, null,
        false, false, now, null, null, false, 1);
    return Decision.of(p, List.of(new PaymentEvent.Voided(now)), List.of(PspAction.VOID));
  }

  public boolean isAwaitingAuthorization() {
    return status == PaymentStatus.PENDING || status == PaymentStatus.UNKNOWN;
  }

  /** AuthorizePayment for an existing payment: re-emit the original reply, or wait. */
  public Decision resendAuthorize() {
    return switch (status) {
      case PENDING, UNKNOWN -> Decision.nothing(this);
      case DECLINED -> Decision.replay(this, List.of(new PaymentEvent.Declined(declineReason, pspReference, changedAt)));
      case VOIDED -> Decision.replay(this, List.of(new PaymentEvent.Voided(changedAt)));
      case AUTHORIZED, CAPTURE_PENDING, CAPTURED, CAPTURE_FAILED ->
          Decision.replay(this, List.of(authorizedEvent()));
    };
  }

  public Decision onAuthorizeResult(AuthorizeResult result, ReconciliationPolicy policy, Instant now) {
    if (!isAwaitingAuthorization()) {
      return Decision.nothing(this);
    }
    return switch (result) {
      case AuthorizeResult.Accepted a ->
          Decision.of(with(PaymentStatus.PENDING, a.pspReference(), now, null, now.plus(policy.pendingCheckAfter())), List.of(), List.of());
      case AuthorizeResult.Declined d -> decline(d.code(), now, List.of());
      case AuthorizeResult.Timeout t ->
          Decision.of(with(PaymentStatus.UNKNOWN, pspReference, now, now.plus(policy.window()), now.plus(policy.interval())), List.of(), List.of());
    };
  }

  public Decision onNotification(Notification n, Instant now) {
    return switch (n) {
      case Notification.AuthorizationSucceeded s -> {
        if (isAwaitingAuthorization()) {
          yield authorize(s.pspReference(), now);
        }
        if ((status == PaymentStatus.DECLINED && declineReason == DeclineCode.PSP_TIMEOUT) || status == PaymentStatus.VOIDED) {
          // A late success after we gave up (or after a void): void it at once; the saga never hears of it.
          Payment p = copy(status, s.pspReference(), declineReason, true, now);
          yield new Decision(p, List.of(), List.of(PspAction.VOID), true, false);
        }
        yield Decision.nothing(this);
      }
      case Notification.AuthorizationFailed f -> isAwaitingAuthorization() ? decline(f.code(), now, List.of()) : Decision.nothing(this);
      case Notification.CaptureSucceeded c -> {
        if (status != PaymentStatus.CAPTURE_PENDING) {
          yield Decision.nothing(this);
        }
        Payment p = copy(PaymentStatus.CAPTURED, pspReference, declineReason, lateSuccessVoided, now);
        yield Decision.of(p, List.of(new PaymentEvent.Captured(amount, pspReference, now)), List.of());
      }
      case Notification.CaptureFailed c -> {
        if (status != PaymentStatus.CAPTURE_PENDING) {
          yield Decision.nothing(this);
        }
        boolean retryable = !c.authorizationExpired();
        Payment p = new Payment(paymentId, orderId, customerId, amount, paymentMethodToken, PaymentStatus.CAPTURE_FAILED,
            pspReference, declineReason, authorizedAt, authorizationExpiresAt, c.authorizationExpired(), retryable, now,
            reconcileDeadline, nextReconcileAt, lateSuccessVoided, version + 1);
        yield Decision.of(p, List.of(new PaymentEvent.CaptureFailed(c.authorizationExpired(), retryable, now)), List.of());
      }
    };
  }

  /** One reconciliation step for an unknown or long-pending outcome. */
  public Decision onReconcile(PspStatus found, ReconciliationPolicy policy, Instant now) {
    if (!isAwaitingAuthorization()) {
      return Decision.nothing(this);
    }
    return switch (found) {
      case PspStatus.Authorized a -> authorize(a.pspReference(), now);
      case PspStatus.Declined d -> decline(d.code(), now, List.of());
      case PspStatus.Pending p -> keepWaiting(policy, now);
      case PspStatus.NotFound nf -> {
        if (status == PaymentStatus.UNKNOWN && !now.isBefore(reconcileDeadline)) {
          // Still unknown after the window: void (safe even if nothing exists) and decline.
          yield decline(DeclineCode.PSP_TIMEOUT, now, List.of(PspAction.VOID));
        }
        yield keepWaiting(policy, now);
      }
    };
  }

  public Decision capture(Instant now) {
    return switch (status) {
      case AUTHORIZED -> Decision.of(copy(PaymentStatus.CAPTURE_PENDING, pspReference, declineReason, lateSuccessVoided, now), List.of(), List.of(PspAction.CAPTURE));
      case CAPTURE_FAILED ->
          captureFailureRetryable
              ? Decision.of(copy(PaymentStatus.CAPTURE_PENDING, pspReference, declineReason, lateSuccessVoided, now), List.of(), List.of(PspAction.CAPTURE))
              : Decision.replay(this, List.of(new PaymentEvent.CaptureFailed(captureFailureAuthExpired, false, changedAt)));
      case CAPTURE_PENDING -> Decision.nothing(this);
      case CAPTURED -> Decision.replay(this, List.of(new PaymentEvent.Captured(amount, pspReference, changedAt)));
      case PENDING, UNKNOWN -> new Decision(this, List.of(), List.of(), false, true);
      case DECLINED, VOIDED -> Decision.replay(this, List.of(new PaymentEvent.CaptureFailed(false, false, now)));
    };
  }

  public Decision voidPayment(Instant now) {
    return switch (status) {
      case PENDING, UNKNOWN, AUTHORIZED, CAPTURE_FAILED -> {
        Payment p = copy(PaymentStatus.VOIDED, pspReference, declineReason, lateSuccessVoided, now);
        yield Decision.of(p, List.of(new PaymentEvent.Voided(now)), List.of(PspAction.VOID));
      }
      // Nothing is held after a decline: confirm so the saga's compensation completes.
      case DECLINED -> Decision.replay(this, List.of(new PaymentEvent.Voided(now)));
      case VOIDED -> Decision.replay(this, List.of(new PaymentEvent.Voided(changedAt)));
      case CAPTURE_PENDING, CAPTURED -> throw new PaymentException("cannot void payment " + paymentId + " in " + status + " (past the pivot)");
    };
  }

  public PaymentEvent.Authorized authorizedEvent() {
    return new PaymentEvent.Authorized(pspReference, amount, authorizedAt, authorizationExpiresAt);
  }

  public Optional<Instant> nextReconcile() {
    return Optional.ofNullable(nextReconcileAt);
  }

  private Decision authorize(String pspRef, Instant now) {
    Payment p = new Payment(paymentId, orderId, customerId, amount, paymentMethodToken, PaymentStatus.AUTHORIZED, pspRef,
        null, now, now.plus(AUTHORIZATION_VALIDITY), false, false, now, null, null, lateSuccessVoided, version + 1);
    return Decision.of(p, List.of(p.authorizedEvent()), List.of());
  }

  private Decision decline(DeclineCode code, Instant now, List<PspAction> actions) {
    Payment p = new Payment(paymentId, orderId, customerId, amount, paymentMethodToken, PaymentStatus.DECLINED, pspReference,
        code, null, null, false, false, now, null, null, lateSuccessVoided, version + 1);
    return Decision.of(p, List.of(new PaymentEvent.Declined(code, pspReference, now)), actions);
  }

  private Decision keepWaiting(ReconciliationPolicy policy, Instant now) {
    Duration next = status == PaymentStatus.UNKNOWN ? policy.interval() : policy.pendingCheckAfter();
    Payment p = new Payment(paymentId, orderId, customerId, amount, paymentMethodToken, status, pspReference, declineReason,
        authorizedAt, authorizationExpiresAt, false, false, changedAt, reconcileDeadline, now.plus(next), lateSuccessVoided, version);
    return new Decision(p, List.of(), List.of(), true, false);
  }

  private Payment with(PaymentStatus s, String pspRef, Instant now, Instant deadline, Instant next) {
    return new Payment(paymentId, orderId, customerId, amount, paymentMethodToken, s, pspRef, declineReason, authorizedAt,
        authorizationExpiresAt, false, false, now, deadline, next, lateSuccessVoided, version);
  }

  private Payment copy(PaymentStatus s, String pspRef, DeclineCode decline, boolean lateVoided, Instant now) {
    return new Payment(paymentId, orderId, customerId, amount, paymentMethodToken, s, pspRef, decline, authorizedAt,
        authorizationExpiresAt, captureFailureAuthExpired, captureFailureRetryable, now, null, null, lateVoided, version + 1);
  }
}
