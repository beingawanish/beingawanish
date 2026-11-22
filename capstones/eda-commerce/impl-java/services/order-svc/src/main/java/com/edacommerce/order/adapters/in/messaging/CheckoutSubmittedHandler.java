package com.edacommerce.order.adapters.in.messaging;

import com.edacommerce.checkout.CheckoutSubmitted;
import com.edacommerce.common.Address;
import com.edacommerce.common.LineItem;
import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.envelope.MessageContext;
import com.edacommerce.kernel.Money;
import com.edacommerce.order.application.OrderSagaService;
import com.edacommerce.order.domain.Order;

/** checkout.events.v1 CheckoutSubmitted: the order saga starts here. */
public record CheckoutSubmittedHandler(OrderSagaService saga) implements MessageHandler<CheckoutSubmitted> {

  @Override
  public Class<CheckoutSubmitted> messageType() {
    return CheckoutSubmitted.class;
  }

  @Override
  public void handle(CheckoutSubmitted c, MessageContext ctx) {
    saga.start(toOrder(c), ctx.eventType(), ctx.eventId(), ctx.causation());
  }

  static Order toOrder(CheckoutSubmitted c) {
    Address a = c.getShippingAddress();
    return new Order(c.getOrderId(), c.getCheckoutId(), c.getCustomerId(),
        c.getLines().stream().map(CheckoutSubmittedHandler::line).toList(),
        money(c.getSubtotal()), money(c.getShippingFee()), money(c.getTax()), money(c.getTotal()),
        new Order.PostalAddress(a.getRecipientName(), a.getLine1(), a.getLine2(), a.getCity(), a.getRegion(), a.getPostalCode(),
            a.getCountryCode(), a.getPhone()),
        c.getContactEmail(), c.getShippingMethod().name(), c.getPaymentMethodToken(), c.getPriceSnapshotAt());
  }

  static Order.OrderLine line(LineItem l) {
    return new Order.OrderLine(l.getLineId(), l.getSku(), l.getProductName(), l.getQuantity(), money(l.getUnitPrice()), money(l.getLineTotal()));
  }

  static Money money(com.edacommerce.common.Money m) {
    return Money.of(m.getAmountMinor(), m.getCurrency());
  }
}
