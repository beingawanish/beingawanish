package com.edacommerce.edacommon.testing;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;

/** A clock tests can move: starts at the real time, {@link #advance} moves it forward. */
public class MutableClock extends Clock {
  private volatile Duration offset = Duration.ZERO;

  public void advance(Duration by) {
    offset = offset.plus(by);
  }

  public void reset() {
    offset = Duration.ZERO;
  }

  @Override
  public ZoneId getZone() {
    return ZoneOffset.UTC;
  }

  @Override
  public Clock withZone(ZoneId zone) {
    return this;
  }

  @Override
  public Instant instant() {
    return Instant.now().plus(offset);
  }
}
