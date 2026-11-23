package com.edacommerce.edacommon.testing;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import org.junit.jupiter.api.extension.ExtendWith;

/**
 * Integration test that needs a real PostgreSQL 16: Testcontainers when Docker is available, else
 * the server named by {@code EDA_TEST_JDBC_URL}. Without either, the test is skipped (not failed).
 */
@Target({ElementType.TYPE, ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
@ExtendWith(PostgresAvailableCondition.class)
public @interface RequiresPostgres {}
