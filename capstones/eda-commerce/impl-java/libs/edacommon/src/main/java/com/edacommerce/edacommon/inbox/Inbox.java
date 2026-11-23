package com.edacommerce.edacommon.inbox;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.lang.Nullable;

/**
 * The inbox table (ADR-0006). The insert runs in the same transaction as the handler's business
 * change; a conflict on (message_id, consumer) means "already processed".
 */
public class Inbox {
  private final JdbcTemplate jdbc;

  public Inbox(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  /** Returns true if this is the first time {@code consumer} sees {@code messageId}. */
  public boolean tryInsert(
      String messageId,
      String consumer,
      String messageType,
      @Nullable String sourceTopic,
      @Nullable Integer sourcePartition,
      @Nullable Long sourceOffset) {
    int rows =
        jdbc.update(
            "INSERT INTO inbox (message_id, consumer, message_type, source_topic, source_partition,"
                + " source_offset) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            messageId,
            consumer,
            messageType,
            sourceTopic,
            sourcePartition,
            sourceOffset);
    return rows == 1;
  }
}
