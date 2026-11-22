package com.edacommerce.edacommon.testing;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.Locale;
import java.util.UUID;
import javax.sql.DataSource;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.lang.Nullable;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.containers.PostgreSQLContainer;

/**
 * Fresh, empty PostgreSQL databases for integration tests. With Docker: one Testcontainers
 * {@code postgres:16-alpine} per JVM, a new database per call. Without Docker: the server named by
 * {@code EDA_TEST_JDBC_URL} (an admin connection URL, e.g. {@code
 * jdbc:postgresql://127.0.0.1:5432/postgres}) with {@code EDA_TEST_JDBC_USER/PASSWORD}.
 */
public final class TestDatabases {
  private TestDatabases() {}

  /** Connection data of one fresh database. */
  public record TestDb(String url, String user, String password) {
    public DataSource dataSource() {
      DriverManagerDataSource ds = new DriverManagerDataSource(url, user, password);
      ds.setDriverClassName("org.postgresql.Driver");
      return ds;
    }

    public void register(DynamicPropertyRegistry registry) {
      registry.add("spring.datasource.url", this::url);
      registry.add("spring.datasource.username", this::user);
      registry.add("spring.datasource.password", this::password);
    }
  }

  private static volatile PostgreSQLContainer<?> container;

  @Nullable
  static String externalUrl() {
    String url = System.getenv("EDA_TEST_JDBC_URL");
    return url == null || url.isBlank() ? null : url;
  }

  static boolean dockerAvailable() {
    try {
      return DockerClientFactory.instance().isDockerAvailable();
    } catch (RuntimeException | LinkageError e) {
      return false;
    }
  }

  public static synchronized TestDb fresh() {
    String admin = externalUrl();
    String user;
    String password;
    if (admin == null) {
      if (container == null) {
        PostgreSQLContainer<?> c =
            new PostgreSQLContainer<>("postgres:16-alpine").withCommand("postgres", "-c", "wal_level=logical");
        c.start();
        container = c;
      }
      admin = container.getJdbcUrl();
      user = container.getUsername();
      password = container.getPassword();
    } else {
      user = env("EDA_TEST_JDBC_USER", "postgres");
      password = env("EDA_TEST_JDBC_PASSWORD", "postgres");
    }
    String name = "t_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16).toLowerCase(Locale.ROOT);
    try (Connection c = DriverManager.getConnection(admin, user, password);
        Statement s = c.createStatement()) {
      s.execute("CREATE DATABASE " + name);
    } catch (SQLException e) {
      throw new IllegalStateException("cannot create test database", e);
    }
    int q = admin.indexOf('?');
    String base = q < 0 ? admin : admin.substring(0, q);
    String params = q < 0 ? "" : admin.substring(q);
    String url = base.substring(0, base.lastIndexOf('/') + 1) + name + params;
    return new TestDb(url, user, password);
  }

  private static String env(String name, String fallback) {
    String v = System.getenv(name);
    return v == null || v.isBlank() ? fallback : v;
  }
}
