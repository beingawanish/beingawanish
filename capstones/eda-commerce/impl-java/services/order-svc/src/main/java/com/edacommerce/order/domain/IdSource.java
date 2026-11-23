package com.edacommerce.order.domain;

/** Mints business ids (UUIDv7 in production); passed in so the domain stays pure. */
@FunctionalInterface
public interface IdSource {
  String next();
}
