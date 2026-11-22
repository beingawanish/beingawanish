package com.edacommerce.payment.adapters.in.messaging;

import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.envelope.MessageContext;
import com.edacommerce.kernel.Money;
import com.edacommerce.payment.AuthorizePayment;
import com.edacommerce.payment.CapturePayment;
import com.edacommerce.payment.RefundPayment;
import com.edacommerce.payment.VoidPayment;
import com.edacommerce.payment.application.PaymentUseCases;

/** Handlers for payment.commands.v1; translation only, no business rules. */
public final class PaymentCommandHandlers {
  private PaymentCommandHandlers() {}

  static Money money(com.edacommerce.common.Money m) {
    return Money.of(m.getAmountMinor(), m.getCurrency());
  }

  /** AuthorizePayment. */
  public record Authorize(PaymentUseCases useCases) implements MessageHandler<AuthorizePayment> {
    @Override
    public Class<AuthorizePayment> messageType() {
      return AuthorizePayment.class;
    }

    @Override
    public void handle(AuthorizePayment c, MessageContext ctx) {
      useCases.authorize(c.getOrderId(), c.getPaymentId(), c.getCustomerId(), money(c.getAmount()), c.getPaymentMethodToken(), ctx.causation());
    }
  }

  /** CapturePayment. */
  public record Capture(PaymentUseCases useCases) implements MessageHandler<CapturePayment> {
    @Override
    public Class<CapturePayment> messageType() {
      return CapturePayment.class;
    }

    @Override
    public void handle(CapturePayment c, MessageContext ctx) {
      useCases.capture(c.getPaymentId(), ctx.causation());
    }
  }

  /** VoidPayment (the saga's compensation). */
  public record VoidCmd(PaymentUseCases useCases) implements MessageHandler<VoidPayment> {
    @Override
    public Class<VoidPayment> messageType() {
      return VoidPayment.class;
    }

    @Override
    public void handle(VoidPayment c, MessageContext ctx) {
      useCases.voidPayment(c.getOrderId(), c.getPaymentId(), Money.zero("EUR"), ctx.causation());
    }
  }

  /** RefundPayment (returns saga). */
  public record RefundCmd(PaymentUseCases useCases) implements MessageHandler<RefundPayment> {
    @Override
    public Class<RefundPayment> messageType() {
      return RefundPayment.class;
    }

    @Override
    public void handle(RefundPayment c, MessageContext ctx) {
      useCases.refund(c.getPaymentId(), c.getRefundId(), c.getReturnId(), money(c.getAmount()), c.getReason(), ctx.causation());
    }
  }
}
