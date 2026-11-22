package com.edacommerce.edacommon.http;

/** One readiness condition (guide §6.5). Readiness never depends on another service. */
public interface ReadinessCheck {
  String name();

  boolean ready();
}
