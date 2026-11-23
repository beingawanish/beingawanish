package com.edacommerce.returns.domain;

/** Mints business ids (UUIDv7 in production) and RMA numbers; passed in to keep the domain pure. */
public interface IdSource {
  String next();

  /** A gapless, human-readable RMA number (RMA-2026-000042). */
  String nextRma();
}
