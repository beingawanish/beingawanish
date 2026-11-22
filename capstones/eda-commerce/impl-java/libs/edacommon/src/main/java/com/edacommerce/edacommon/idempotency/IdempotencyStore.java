package com.edacommerce.edacommon.idempotency;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.lang.Nullable;

/** The {@code idempotency_key} table (common-tables.sql). */
public class IdempotencyStore {

  /** A stored key. */
  @SuppressWarnings("ArrayRecordComponent") // bytes are opaque payloads, never compared
  public record StoredKey(
      String requestHash,
      String status,
      @Nullable Integer responseStatus,
      Map<String, String> responseHeaders,
      @Nullable byte[] responseBody) {
    public boolean completed() {
      return "COMPLETED".equals(status);
    }
  }

  private static final TypeReference<Map<String, String>> HEADERS = new TypeReference<>() {};
  private final JdbcTemplate jdbc;
  private final ObjectMapper json = new ObjectMapper();

  public IdempotencyStore(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  /**
   * Transaction-scoped advisory lock on (caller, key). A concurrent request with the same key gets
   * false at once (and answers 409) instead of queueing behind the first one.
   */
  public boolean tryLock(String caller, String key) {
    Boolean locked =
        jdbc.queryForObject(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(? || chr(10) || ?, 0))",
            Boolean.class,
            caller,
            key);
    return Boolean.TRUE.equals(locked);
  }

  public Optional<StoredKey> find(String caller, String key, Instant now) {
    return jdbc.query(
            "SELECT request_hash, status, response_status, response_headers::text AS headers, response_body"
                + " FROM idempotency_key WHERE caller = ? AND key = ? AND expires_at > ?",
            (rs, i) ->
                new StoredKey(
                    rs.getString("request_hash"),
                    rs.getString("status"),
                    (Integer) rs.getObject("response_status"),
                    parse(rs.getString("headers")),
                    rs.getBytes("response_body")),
            caller,
            key,
            Timestamp.from(now))
        .stream()
        .findFirst();
  }

  public void begin(String caller, String key, String requestHash, Instant now, Instant expiresAt) {
    // An expired row for the same key may still exist until housekeeping runs.
    jdbc.update("DELETE FROM idempotency_key WHERE caller = ? AND key = ? AND expires_at <= ?", caller, key, Timestamp.from(now));
    jdbc.update(
        "INSERT INTO idempotency_key (caller, key, request_hash, status, created_at, expires_at)"
            + " VALUES (?, ?, ?, 'IN_PROGRESS', ?, ?)",
        caller,
        key,
        requestHash,
        Timestamp.from(now),
        Timestamp.from(expiresAt));
  }

  public void complete(String caller, String key, int status, Map<String, String> headers, byte[] body) {
    String headersJson;
    try {
      headersJson = json.writeValueAsString(headers);
    } catch (JsonProcessingException e) {
      throw new IllegalStateException(e);
    }
    jdbc.update(
        "UPDATE idempotency_key SET status = 'COMPLETED', response_status = ?, response_headers = ?::jsonb,"
            + " response_body = ? WHERE caller = ? AND key = ?",
        status,
        headersJson,
        body,
        caller,
        key);
  }

  private Map<String, String> parse(@Nullable String headers) {
    if (headers == null) {
      return Map.of();
    }
    try {
      return json.readValue(headers, HEADERS);
    } catch (JsonProcessingException e) {
      return Map.of();
    }
  }
}
