package com.edacommerce.order.domain;

import com.edacommerce.kernel.Money;
import java.time.Instant;
import java.time.ZoneOffset;

/** An invoice: a legal document about an order (architecture §3, owned by order-svc). */
public record Invoice(
    String invoiceId,
    String orderId,
    String invoiceNumber,
    Money total,
    Instant issuedAt,
    String bucket,
    String objectKey,
    long sizeBytes,
    String sha256) {

  /** Gapless per year (guide §6.2): {@code INV-2026-000123}. */
  public static String number(int year, long sequence) {
    return String.format("INV-%04d-%06d", year, sequence);
  }

  public static int yearOf(Instant at) {
    return at.atZone(ZoneOffset.UTC).getYear();
  }
}
