package com.edacommerce.edacommon.testing;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import javax.sql.DataSource;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * Checklist item "shared tables created by migration 1 match contracts/sql/common-tables.sql": the
 * contract DDL is applied to a fresh database and {@code information_schema.columns} (plus indexes
 * and the publication) is compared with a database migrated by the service.
 */
public final class SharedTables {
  private SharedTables() {}

  public static final List<String> TABLES =
      List.of("outbox", "inbox", "idempotency_key", "saga_instance", "saga_transition");

  public static void assertMatchesContract(DataSource migrated) {
    TestDatabases.TestDb reference = TestDatabases.fresh();
    JdbcTemplate ref = new JdbcTemplate(reference.dataSource());
    ref.execute(Contracts.commonTablesSql());
    JdbcTemplate svc = new JdbcTemplate(migrated);
    assertThat(columns(svc)).as("shared table columns").isEqualTo(columns(ref));
    assertThat(indexes(svc)).as("shared table indexes").containsAll(indexes(ref));
    assertThat(svc.queryForList("SELECT pubname FROM pg_publication", String.class)).contains("outbox_pub");
  }

  static List<String> columns(JdbcTemplate jdbc) {
    return jdbc.queryForList(
        "SELECT table_name || '.' || column_name || ' ' || data_type || ' nullable=' || is_nullable"
            + " || ' default=' || coalesce(column_default, '') FROM information_schema.columns"
            + " WHERE table_schema = 'public' AND table_name = ANY (?) ORDER BY table_name, ordinal_position",
        String.class,
        (Object) TABLES.toArray(String[]::new));
  }

  static List<String> indexes(JdbcTemplate jdbc) {
    return jdbc.queryForList(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = ANY (?) ORDER BY indexname",
        String.class,
        (Object) TABLES.toArray(String[]::new));
  }
}
