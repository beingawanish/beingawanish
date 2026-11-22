package com.edacommerce.edacommon.ids;

import com.github.f4b6a3.uuid.UuidCreator;

/** UUIDv7 (RFC 9562), lower-case text form, for every id we mint (guide §6.2). */
public final class Ids {
  private Ids() {}

  public static String newId() {
    return UuidCreator.getTimeOrderedEpoch().toString();
  }
}
