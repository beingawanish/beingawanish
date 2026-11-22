package com.edacommerce.edacommon.outbox;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * Keeps the shared tables bounded: outbox rows older than 7 days (ADR-0003), inbox rows older than
 * 100 days (ADR-0006: longest retention 90 days plus margin), expired idempotency keys (ADR-0012).
 */
public class Housekeeping {
  private static final Logger log = LoggerFactory.getLogger(Housekeeping.class);
  private final JdbcTemplate jdbc;

  public Housekeeping(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  public void run() {
    int outbox = jdbc.update("DELETE FROM outbox WHERE created_at < now() - interval '7 days'");
    int inbox = jdbc.update("DELETE FROM inbox WHERE received_at < now() - interval '100 days'");
    int keys = jdbc.update("DELETE FROM idempotency_key WHERE expires_at < now()");
    if (outbox + inbox + keys > 0) {
      log.info(
          "housekeeping deleted {} outbox, {} inbox, {} idempotency rows", outbox, inbox, keys);
    }
  }
}
