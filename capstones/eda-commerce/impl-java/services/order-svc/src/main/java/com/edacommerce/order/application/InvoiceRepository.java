package com.edacommerce.order.application;

import com.edacommerce.order.domain.Invoice;
import java.util.Optional;

/** Port: invoices and the gapless per-year counter. */
public interface InvoiceRepository {
  Optional<Invoice> findByOrder(String orderId);

  Optional<Invoice> find(String invoiceId);

  /** Locks the year's counter row ({@code SELECT ... FOR UPDATE}) and returns the next number. */
  long nextSequence(int year);

  void save(Invoice invoice);
}
