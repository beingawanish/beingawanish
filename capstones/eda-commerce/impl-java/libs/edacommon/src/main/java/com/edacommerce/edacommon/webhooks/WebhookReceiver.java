package com.edacommerce.edacommon.webhooks;

import com.edacommerce.edacommon.inbox.Inbox;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import org.springframework.http.HttpStatus;
import org.springframework.lang.Nullable;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * The store-then-ack part of every webhook endpoint (webhooks.yaml rules 1-3): verify, inbox-dedupe
 * on the provider event id, store the raw payload in the same transaction, answer quickly. Domain
 * processing happens afterwards from the stored row, so a slow database never causes provider retries.
 */
public class WebhookReceiver {

  /** Persists the raw payload in the service's own webhook table. */
  @FunctionalInterface
  public interface Store {
    void store(String providerEventId, byte[] rawBody);
  }

  /** What the endpoint should answer. */
  public enum Result {
    ACCEPTED(HttpStatus.OK),
    DUPLICATE(HttpStatus.OK),
    REJECTED(HttpStatus.UNAUTHORIZED);

    private final HttpStatus status;

    Result(HttpStatus status) {
      this.status = status;
    }

    public HttpStatus status() {
      return status;
    }
  }

  private final String source;
  private final WebhookVerifier verifier;
  private final Inbox inbox;
  private final TransactionTemplate tx;
  private final EdaMetrics metrics;

  /**
   * @param source {@code psp} or {@code carrier}; the inbox consumer is {@code <source>-webhook}
   */
  public WebhookReceiver(
      String source, WebhookVerifier verifier, Inbox inbox, TransactionTemplate tx, EdaMetrics metrics) {
    this.source = source;
    this.verifier = verifier;
    this.inbox = inbox;
    this.tx = tx;
    this.metrics = metrics;
  }

  public boolean authentic(@Nullable String timestamp, @Nullable String signature, byte[] body) {
    if (verifier.rejectionReason(timestamp, signature, body) != null) {
      metrics.webhookReceived(source, "rejected");
      return false;
    }
    return true;
  }

  /** Call after {@link #authentic} and after parsing the provider event id from the body. */
  public Result receive(String providerEventId, String messageType, byte[] body, Store store) {
    Boolean fresh =
        tx.execute(
            status -> {
              if (!inbox.tryInsert(providerEventId, source + "-webhook", messageType, null, null, null)) {
                return Boolean.FALSE;
              }
              store.store(providerEventId, body);
              return Boolean.TRUE;
            });
    Result result = Boolean.TRUE.equals(fresh) ? Result.ACCEPTED : Result.DUPLICATE;
    metrics.webhookReceived(source, result == Result.ACCEPTED ? "accepted" : "duplicate");
    return result;
  }
}
