package com.edacommerce.checkout.application;

import com.edacommerce.checkout.domain.Cart;
import com.edacommerce.checkout.domain.CatalogEntry;
import com.edacommerce.kernel.Money;
import java.time.Instant;
import java.util.Collection;
import java.util.Map;
import java.util.Optional;

/** Ports of checkout-svc. */
public final class CheckoutPorts {
  private CheckoutPorts() {}

  /** Carts. */
  public interface CartRepository {
    Optional<Cart> findForUpdate(String cartId);

    Optional<Cart> find(String cartId);

    void save(Cart cart);
  }

  /** The catalog read model fed by the compacted topics; each part is version-guarded. */
  public interface CatalogView {
    Map<String, CatalogEntry> find(Collection<String> skus);

    boolean applyProduct(String sku, String name, boolean active, long version, Instant at);

    boolean applyPrice(String sku, Money list, Money sale, long version, Instant at);

    boolean applyStock(String sku, int available, long version, Instant at);
  }

  /** Submitted checkouts. */
  public interface CheckoutRepository {
    void insert(
        String checkoutId,
        String orderId,
        String cartId,
        String customerId,
        Money total,
        Instant at);

    void updateStatus(String orderId, String status);
  }
}
