package com.edacommerce.payment.domain;

/** A call the application must make to the PSP after the domain decided. */
public enum PspAction {
  CAPTURE,
  VOID
}
