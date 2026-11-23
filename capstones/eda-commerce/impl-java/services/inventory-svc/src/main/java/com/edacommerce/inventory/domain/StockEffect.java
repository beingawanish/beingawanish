package com.edacommerce.inventory.domain;

/**
 * A change to one stock row, decided by the domain and applied by the persistence adapter with a
 * conditional update (stock can never go negative).
 */
public sealed interface StockEffect {
  String sku();

  int quantity();

  /** reserved += q, only if on_hand - reserved >= q. */
  record Reserve(String sku, int quantity) implements StockEffect {}

  /** reserved -= q (a held reservation was released or expired). */
  record Unreserve(String sku, int quantity) implements StockEffect {}

  /** on_hand -= q and reserved -= q (a held reservation became an allocation). */
  record Allocate(String sku, int quantity) implements StockEffect {}

  /** on_hand += q (a committed allocation was released, or a return was restocked). */
  record Return(String sku, int quantity) implements StockEffect {}
}
