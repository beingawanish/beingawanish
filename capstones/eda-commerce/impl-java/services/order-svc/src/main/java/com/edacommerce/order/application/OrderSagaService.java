package com.edacommerce.order.application;

import com.edacommerce.common.ClaimCheck;
import com.edacommerce.edacommon.claimcheck.ClaimCheckStore;
import com.edacommerce.edacommon.claimcheck.ClaimChecks;
import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.errors.RetryLaterException;
import com.edacommerce.edacommon.saga.SagaEngine;
import com.edacommerce.edacommon.saga.SagaOperator;
import com.edacommerce.edacommon.saga.SagaRow;
import com.edacommerce.edacommon.saga.SagaStep;
import com.edacommerce.order.domain.IdSource;
import com.edacommerce.order.domain.Invoice;
import com.edacommerce.order.domain.Order;
import com.edacommerce.order.domain.OrderEvent;
import com.edacommerce.order.domain.OrderSaga;
import com.edacommerce.order.domain.OrderSagaCommand;
import com.edacommerce.order.domain.OrderSagaState;
import com.edacommerce.order.domain.OrderSagaTrigger;
import com.edacommerce.order.domain.OrderStatus;
import com.edacommerce.order.domain.SagaTimeouts;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.springframework.lang.Nullable;

/**
 * The order saga's use cases on top of the edacommon saga engine: one transaction per trigger, in
 * which the saga row, the transition row, the order status, the invoice (when issued) and all
 * outgoing commands and events commit together with the consumer's inbox row (guide §4.2).
 */
public class OrderSagaService implements SagaOperator {
  public static final String SAGA_TYPE = "ORDER";
  public static final String INVOICE_BUCKET = "invoices";

  private final SagaEngine engine;
  private final OrderRepository orders;
  private final InvoiceRepository invoices;
  private final InvoiceRenderer renderer;
  private final ClaimCheckStore documents;
  private final SagaDataCodec codec;
  private final IdSource ids;
  private final SagaTimeouts timeouts;
  private final Clock clock;

  public OrderSagaService(
      SagaEngine engine,
      OrderRepository orders,
      InvoiceRepository invoices,
      InvoiceRenderer renderer,
      ClaimCheckStore documents,
      SagaDataCodec codec,
      IdSource ids,
      SagaTimeouts timeouts,
      Clock clock) {
    this.engine = engine;
    this.orders = orders;
    this.invoices = invoices;
    this.renderer = renderer;
    this.documents = documents;
    this.codec = codec;
    this.ids = ids;
    this.timeouts = timeouts;
    this.clock = clock;
  }

  /** CheckoutSubmitted: create the order and start the saga. A repeated checkout is ignored. */
  public SagaEngine.Result start(
      Order order, String triggerType, String triggerId, Causation causation) {
    return engine.handle(
        SAGA_TYPE,
        order.orderId(),
        triggerType,
        triggerId,
        causation,
        order.orderId(),
        (current, now) -> {
          if (current.isPresent()) {
            return SagaStep.ignore();
          }
          orders.insert(order);
          OrderSaga.Decision d = OrderSaga.start(order.orderId(), order.total(), context(now));
          return toStep(d, order, 0, now);
        });
  }

  /** Any reply, event, deadline or operator action for an existing saga. */
  public SagaEngine.Result handle(
      String orderId,
      OrderSagaTrigger trigger,
      String triggerType,
      @Nullable String triggerId,
      @Nullable Causation causation) {
    return engine.handle(
        SAGA_TYPE,
        orderId,
        triggerType,
        triggerId,
        causation,
        null,
        (current, now) -> {
          if (current.isEmpty()) {
            // The CheckoutSubmitted may still be in a retry topic (ADR-0007 reorders retried
            // records).
            throw new RetryLaterException("no saga yet for order " + orderId);
          }
          SagaRow row = current.get();
          OrderSaga.Snapshot snapshot =
              new OrderSaga.Snapshot(
                  OrderSagaState.valueOf(row.state()),
                  codec.read(row.data()),
                  row.deadlineAt(),
                  row.stepAttempts());
          OrderSaga.Decision d = OrderSaga.apply(snapshot, trigger, context(now));
          if (d.ignored()) {
            return SagaStep.ignore();
          }
          Order order =
              orders
                  .find(orderId)
                  .orElseThrow(() -> new IllegalStateException("saga without order " + orderId));
          return toStep(d, order, row.version(), now);
        });
  }

  public void onDeadline(String orderId) {
    handle(orderId, new OrderSagaTrigger.Deadline(), "DEADLINE", null, null);
  }

  @Override
  public RetryOutcome retryStep(String sagaId) {
    Optional<OrderStatus> status = orders.status(sagaId);
    if (status.isEmpty()) {
      return RetryOutcome.NOT_FOUND;
    }
    if (status.get() == OrderStatus.DELIVERED || status.get() == OrderStatus.CANCELLED) {
      return RetryOutcome.TERMINAL;
    }
    SagaEngine.Result r =
        handle(sagaId, new OrderSagaTrigger.OperatorRetry(), "OPERATOR", null, null);
    return r == SagaEngine.Result.APPLIED ? RetryOutcome.ACCEPTED : RetryOutcome.NOT_APPLICABLE;
  }

  private OrderSaga.Context context(Instant now) {
    return new OrderSaga.Context(now, ids, timeouts);
  }

  private SagaStep toStep(OrderSaga.Decision d, Order order, long currentVersion, Instant now) {
    long sagaVersion = currentVersion + 1;
    List<OutgoingMessage> messages = new ArrayList<>();
    for (OrderEvent e : d.events()) {
      if (e instanceof OrderEvent.InvoiceToIssue inv) {
        messages.add(issueInvoice(order, inv, now));
      } else {
        messages.add(OrderMessages.event(e, order, d.data(), now));
      }
    }
    for (OrderSagaCommand c : d.commands()) {
      messages.add(OrderMessages.command(c, order, sagaVersion));
    }
    orders.updateStatus(order.orderId(), OrderStatus.of(d.state()));
    String outcome =
        d.state() == OrderSagaState.DELIVERED
            ? "DELIVERED"
            : d.state() == OrderSagaState.CANCELLED ? "CANCELLED" : null;
    return new SagaStep(
        false,
        d.state().name(),
        codec.write(d.data()),
        d.deadlineAt(),
        d.stepAttempts(),
        messages,
        outcome,
        d.attention(),
        d.timeout(),
        d.decisionReached());
  }

  /**
   * Renders the invoice, stores it under a deterministic key (a retry overwrites the same object)
   * before the transaction commits, and allocates the gapless number in the same transaction
   * (object first, event second: ADR-0009, guide §6.2).
   */
  private OutgoingMessage issueInvoice(Order order, OrderEvent.InvoiceToIssue inv, Instant now) {
    Invoice existing = invoices.find(inv.invoiceId()).orElse(null);
    Invoice invoice;
    ClaimCheck document;
    if (existing != null) {
      invoice = existing;
      document =
          ClaimCheck.newBuilder()
              .setBucket(existing.bucket())
              .setObjectKey(existing.objectKey())
              .setContentType("application/pdf")
              .setSizeBytes(existing.sizeBytes())
              .setSha256(existing.sha256())
              .setExpiresAt(null)
              .build();
    } else {
      int year = Invoice.yearOf(now);
      String number = Invoice.number(year, invoices.nextSequence(year));
      byte[] pdf = renderer.render(order, number, now);
      String key = ClaimChecks.key("order", now, order.orderId(), inv.invoiceId(), "pdf");
      document = documents.put(INVOICE_BUCKET, key, pdf, "application/pdf", null);
      invoice =
          new Invoice(
              inv.invoiceId(),
              order.orderId(),
              number,
              order.total(),
              now,
              INVOICE_BUCKET,
              key,
              document.getSizeBytes(),
              document.getSha256());
      invoices.save(invoice);
    }
    return OrderMessages.invoiceIssued(invoice, document, inv.version());
  }

  /** For tests and the read side. */
  public Clock clock() {
    return clock;
  }
}
