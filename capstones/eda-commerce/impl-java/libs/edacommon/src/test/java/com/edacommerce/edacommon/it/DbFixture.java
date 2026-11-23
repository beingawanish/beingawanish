package com.edacommerce.edacommon.it;

import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.inbox.Inbox;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.edacommon.serde.AvroSerde;
import com.edacommerce.edacommon.testing.Contracts;
import com.edacommerce.edacommon.testing.InMemorySchemaRegistry;
import com.edacommerce.edacommon.testing.TestDatabases;
import com.edacommerce.edacommon.testing.TestTelemetry;
import com.edacommerce.edacommon.tracing.MessagingTracing;
import com.zaxxer.hikari.HikariDataSource;
import java.time.Clock;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** A fresh database with the shared tables from the contract DDL, and edacommon wired by hand. */
final class DbFixture implements AutoCloseable {
  final HikariDataSource dataSource = new HikariDataSource();
  final JdbcTemplate jdbc;
  final TransactionTemplate tx;
  final InMemorySchemaRegistry registry = new InMemorySchemaRegistry();
  final AvroSerde serde = new AvroSerde(registry);
  final TestTelemetry telemetry = new TestTelemetry();
  final EdaMetrics metrics = new EdaMetrics(telemetry.openTelemetry());
  final MessagingTracing tracing = new MessagingTracing(telemetry.openTelemetry());
  final Clock clock = Clock.systemUTC();
  final OutboxWriter outbox;
  final Inbox inbox;

  DbFixture() {
    TestDatabases.TestDb db = TestDatabases.fresh();
    dataSource.setJdbcUrl(db.url());
    dataSource.setUsername(db.user());
    dataSource.setPassword(db.password());
    dataSource.setMaximumPoolSize(8);
    jdbc = new JdbcTemplate(dataSource);
    jdbc.execute(Contracts.commonTablesSql());
    jdbc.execute("CREATE TABLE effect (id text PRIMARY KEY, n int NOT NULL)");
    tx = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
    outbox = new OutboxWriter(jdbc, serde, clock, IdGenerator.uuidV7(), "test-svc");
    inbox = new Inbox(jdbc);
  }

  int count(String sql, Object... args) {
    Integer n = jdbc.queryForObject(sql, Integer.class, args);
    return n == null ? 0 : n;
  }

  @Override
  public void close() {
    dataSource.close();
  }
}
