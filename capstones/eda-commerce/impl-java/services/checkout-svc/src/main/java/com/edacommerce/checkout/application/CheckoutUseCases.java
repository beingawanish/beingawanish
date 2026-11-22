package com.edacommerce.checkout.application;

import com.edacommerce.checkout.CheckoutSubmitted;
import com.edacommerce.checkout.application.CheckoutPorts.CartRepository;
import com.edacommerce.checkout.application.CheckoutPorts.CatalogView;
import com.edacommerce.checkout.application.CheckoutPorts.CheckoutRepository;
import com.edacommerce.checkout.domain.Cart;
import com.edacommerce.checkout.domain.CheckoutException;
import com.edacommerce.checkout.domain.Pricing;
import com.edacommerce.common.Address;
import com.edacommerce.common.LineItem;
import com.edacommerce.common.ShippingMethod;
import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.kernel.Money;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.transaction.annotation.Transactional;

/** Cart and checkout use cases. */
public class CheckoutUseCases {
  public static final String TOPIC = "checkout.events.v1";

  /** What the client sends to POST /checkouts (validated by the HTTP adapter). */
  public record SubmitCommand(
      String cartId,
      Address shippingAddress,
      String contactEmail,
      String shippingMethod,
      String paymentMethodToken,
      Money expectedTotal) {}

  /** The 202 answer. */
  public record Accepted(String checkoutId, String orderId, Money total) {}

  private final CartRepository carts;
  private final CatalogView catalog;
  private final CheckoutRepository checkouts;
  private final OutboxWriter outbox;
  private final IdGenerator ids;
  private final Clock clock;

  public CheckoutUseCases(
      CartRepository carts,
      CatalogView catalog,
      CheckoutRepository checkouts,
      OutboxWriter outbox,
      IdGenerator ids,
      Clock clock) {
    this.carts = carts;
    this.catalog = catalog;
    this.checkouts = checkouts;
    this.outbox = outbox;
    this.ids = ids;
    this.clock = clock;
  }

  @Transactional
  public Cart create(String customerId, String currency) {
    Cart cart = Cart.open(ids.newId(), customerId, currency);
    carts.save(cart);
    return cart;
  }

  public Optional<Cart> find(String cartId, String customerId) {
    return carts.find(cartId).filter(c -> c.customerId().equals(customerId));
  }

  public Pricing.Priced price(Cart cart) {
    return Pricing.price(cart, catalog.find(cart.lines().keySet()), null, clock.instant());
  }

  /** PUT item; {@code ifMatch} is the version the client last saw, or null. */
  @Transactional
  public Cart setItem(String cartId, String customerId, String sku, int quantity, Long ifMatch) {
    Cart cart = owned(cartId, customerId);
    checkVersion(cart, ifMatch);
    Cart next = cart.setItem(catalog.find(List.of(sku)).get(sku), quantity);
    carts.save(next);
    return next;
  }

  @Transactional
  public Cart removeItem(String cartId, String customerId, String sku) {
    Cart next = owned(cartId, customerId).removeItem(sku);
    carts.save(next);
    return next;
  }

  /**
   * POST /checkouts: freeze prices, check expectedTotal (ADR-0012: a stale view never charges a
   * surprise amount), mint the orderId and write CheckoutSubmitted to the outbox in the same
   * transaction as the checkout row and the idempotency key.
   */
  @Transactional
  public Accepted submit(String customerId, SubmitCommand cmd) {
    Cart cart =
        carts
            .findForUpdate(cmd.cartId())
            .filter(c -> c.customerId().equals(customerId))
            .orElseThrow(
                () ->
                    new CheckoutException("cart-not-found", "cart " + cmd.cartId() + " not found"));
    if (cart.status() != Cart.Status.OPEN) {
      throw new CheckoutException(
          "cart-already-checked-out", "cart " + cart.cartId() + " is " + cart.status());
    }
    if (cart.lines().isEmpty()) {
      throw new CheckoutException("cart-empty", "the cart is empty");
    }
    Instant now = clock.instant();
    Pricing.Priced priced =
        Pricing.price(cart, catalog.find(cart.lines().keySet()), cmd.shippingMethod(), now);
    if (!priced.unsellable().isEmpty()) {
      throw new CheckoutException(
          "discontinued-sku", "cannot sell: " + String.join(", ", priced.unsellable()));
    }
    if (!priced.total().equals(cmd.expectedTotal())) {
      throw new CheckoutException(
          "price-mismatch",
          "expected total "
              + cmd.expectedTotal().amountMinor()
              + " but the cart now costs "
              + priced.total().amountMinor()
              + " "
              + priced.total().currency());
    }
    String orderId = ids.newId();
    String checkoutId = ids.newId();
    carts.save(cart.checkedOut());
    checkouts.insert(checkoutId, orderId, cart.cartId(), customerId, priced.total(), now);
    CheckoutSubmitted event =
        CheckoutSubmitted.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setCheckoutId(checkoutId)
            .setOrderId(orderId)
            .setCartId(cart.cartId())
            .setCustomerId(customerId)
            .setLines(
                priced.lines().stream()
                    .map(
                        l ->
                            new LineItem(
                                l.lineId(),
                                l.sku(),
                                l.productName(),
                                l.quantity(),
                                money(l.unitPrice()),
                                money(l.lineTotal())))
                    .toList())
            .setSubtotal(money(priced.subtotal()))
            .setShippingFee(money(priced.shippingFee()))
            .setTax(money(priced.tax()))
            .setTotal(money(priced.total()))
            .setShippingAddress(cmd.shippingAddress())
            .setContactEmail(cmd.contactEmail())
            .setShippingMethod(ShippingMethod.valueOf(cmd.shippingMethod()))
            .setPaymentMethodToken(cmd.paymentMethodToken())
            .setPriceSnapshotAt(priced.pricedAt())
            .build();
    // Key orderId (the saga's partition key from the first event); aggregate Checkout/checkoutId.
    outbox.append(
        OutgoingMessage.of(TOPIC, orderId, event, "Checkout", checkoutId, 1),
        Causation.root(orderId));
    return new Accepted(checkoutId, orderId, priced.total());
  }

  @Transactional
  public void orderOutcome(String orderId, String status) {
    checkouts.updateStatus(orderId, status);
  }

  private Cart owned(String cartId, String customerId) {
    return carts
        .findForUpdate(cartId)
        .filter(c -> c.customerId().equals(customerId))
        .orElseThrow(() -> new CheckoutException("not-found", "cart " + cartId + " not found"));
  }

  private static void checkVersion(Cart cart, Long ifMatch) {
    if (ifMatch != null && ifMatch != cart.version()) {
      throw new CheckoutException("precondition-failed", "cart version is " + cart.version());
    }
  }

  static com.edacommerce.common.Money money(Money m) {
    return new com.edacommerce.common.Money(m.amountMinor(), m.currency());
  }
}
