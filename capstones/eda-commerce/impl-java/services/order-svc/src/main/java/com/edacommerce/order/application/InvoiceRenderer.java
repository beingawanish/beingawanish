package com.edacommerce.order.application;

import com.edacommerce.order.domain.Order;
import java.time.Instant;

/** Port: renders the invoice document (OpenPDF adapter). */
public interface InvoiceRenderer {
  byte[] render(Order order, String invoiceNumber, Instant issuedAt);
}
