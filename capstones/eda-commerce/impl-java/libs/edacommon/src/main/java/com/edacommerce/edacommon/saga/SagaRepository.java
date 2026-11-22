package com.edacommerce.edacommon.saga;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.lang.Nullable;

/**
 * Saga persistence on the shared tables (ADR-0008): row lock on load, optimistic version check on
 * save, one transition row per state change.
 */
public class SagaRepository {
  static final String COLUMNS =
      "saga_id, saga_type, state, data::text AS data, version, deadline_at, step_attempts,"
          + " correlation_id, created_at, updated_at, completed_at";

  private final JdbcTemplate jdbc;

  public SagaRepository(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  public Optional<SagaRow> find(String sagaId) {
    return jdbc
        .query(
            "SELECT " + COLUMNS + " FROM saga_instance WHERE saga_id = ?",
            SagaRepository::row,
            sagaId)
        .stream()
        .findFirst();
  }

  /** {@code SELECT ... FOR UPDATE}: serialises concurrent triggers for one saga. */
  public Optional<SagaRow> loadForUpdate(String sagaId) {
    return jdbc
        .query(
            "SELECT " + COLUMNS + " FROM saga_instance WHERE saga_id = ? FOR UPDATE",
            SagaRepository::row,
            sagaId)
        .stream()
        .findFirst();
  }

  public void insert(SagaRow row) {
    jdbc.update(
        "INSERT INTO saga_instance (saga_id, saga_type, state, data, version, deadline_at, step_attempts,"
            + " correlation_id, created_at, updated_at, completed_at)"
            + " VALUES (?, ?, ?, ?::jsonb, ?, ?, ?, ?, ?, ?, ?)",
        row.sagaId(),
        row.sagaType(),
        row.state(),
        row.data(),
        row.version(),
        ts(row.deadlineAt()),
        row.stepAttempts(),
        row.correlationId(),
        ts(row.createdAt()),
        ts(row.updatedAt()),
        ts(row.completedAt()));
  }

  /** Saves {@code row} if the stored version is still {@code expectedVersion}. */
  public void update(SagaRow row, long expectedVersion) {
    int n =
        jdbc.update(
            "UPDATE saga_instance SET state = ?, data = ?::jsonb, version = ?, deadline_at = ?,"
                + " step_attempts = ?, updated_at = ?, completed_at = ? WHERE saga_id = ? AND version = ?",
            row.state(),
            row.data(),
            row.version(),
            ts(row.deadlineAt()),
            row.stepAttempts(),
            ts(row.updatedAt()),
            ts(row.completedAt()),
            row.sagaId(),
            expectedVersion);
    if (n != 1) {
      throw new OptimisticLockingFailureException(
          "saga "
              + row.sagaId()
              + " changed concurrently (expected version "
              + expectedVersion
              + ")");
    }
  }

  public void appendTransition(SagaTransitionRow t) {
    jdbc.update(
        "INSERT INTO saga_transition (saga_id, seq, from_state, to_state, trigger_type, trigger_id, at)"
            + " VALUES (?, ?, ?, ?, ?, ?, ?)",
        t.sagaId(),
        t.seq(),
        t.fromState(),
        t.toState(),
        t.triggerType(),
        t.triggerId(),
        ts(t.at()));
  }

  public List<SagaTransitionRow> history(String sagaId) {
    return jdbc.query(
        "SELECT saga_id, seq, from_state, to_state, trigger_type, trigger_id, at FROM saga_transition"
            + " WHERE saga_id = ? ORDER BY seq",
        (rs, i) ->
            new SagaTransitionRow(
                rs.getString("saga_id"),
                rs.getLong("seq"),
                rs.getString("from_state"),
                rs.getString("to_state"),
                rs.getString("trigger_type"),
                rs.getString("trigger_id"),
                rs.getTimestamp("at").toInstant()),
        sagaId);
  }

  /** When the saga last entered {@code state} (for the per-step duration metric). */
  public Optional<Instant> enteredStateAt(String sagaId, String state) {
    Timestamp t =
        jdbc.queryForObject(
            "SELECT max(at) FROM saga_transition WHERE saga_id = ? AND to_state = ? AND from_state <> to_state",
            Timestamp.class,
            sagaId,
            state);
    return Optional.ofNullable(t).map(Timestamp::toInstant);
  }

  /**
   * Locks one due saga, skipping rows other sweepers hold, excluding ids already handled this pass.
   */
  public Optional<String> lockNextDue(String sagaType, Instant now, List<String> exclude) {
    return jdbc
        .query(
            "SELECT saga_id FROM saga_instance WHERE saga_type = ? AND deadline_at <= ?"
                + " AND NOT (saga_id = ANY (?)) ORDER BY deadline_at LIMIT 1 FOR UPDATE SKIP LOCKED",
            ps -> {
              ps.setString(1, sagaType);
              ps.setTimestamp(2, Timestamp.from(now));
              ps.setArray(3, ps.getConnection().createArrayOf("text", exclude.toArray()));
            },
            (rs, i) -> rs.getString(1))
        .stream()
        .findFirst();
  }

  public long countOverdue(String sagaType, Instant threshold) {
    Long n =
        jdbc.queryForObject(
            "SELECT count(*) FROM saga_instance WHERE saga_type = ? AND deadline_at < ?",
            Long.class,
            sagaType,
            Timestamp.from(threshold));
    return n == null ? 0 : n;
  }

  private static SagaRow row(ResultSet rs, int i) throws SQLException {
    return new SagaRow(
        rs.getString("saga_id"),
        rs.getString("saga_type"),
        rs.getString("state"),
        rs.getString("data"),
        rs.getLong("version"),
        instant(rs.getTimestamp("deadline_at")),
        rs.getInt("step_attempts"),
        rs.getString("correlation_id"),
        rs.getTimestamp("created_at").toInstant(),
        rs.getTimestamp("updated_at").toInstant(),
        instant(rs.getTimestamp("completed_at")));
  }

  @Nullable
  private static Instant instant(@Nullable Timestamp t) {
    return t == null ? null : t.toInstant();
  }

  @Nullable
  private static Timestamp ts(@Nullable Instant i) {
    return i == null ? null : Timestamp.from(i);
  }
}
