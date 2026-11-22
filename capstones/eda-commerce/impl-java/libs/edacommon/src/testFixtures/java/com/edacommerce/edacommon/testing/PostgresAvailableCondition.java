package com.edacommerce.edacommon.testing;

import org.junit.jupiter.api.extension.ConditionEvaluationResult;
import org.junit.jupiter.api.extension.ExecutionCondition;
import org.junit.jupiter.api.extension.ExtensionContext;

/** Skips cleanly when neither Docker nor EDA_TEST_JDBC_URL is available. */
public class PostgresAvailableCondition implements ExecutionCondition {
  @Override
  public ConditionEvaluationResult evaluateExecutionCondition(ExtensionContext context) {
    if (TestDatabases.externalUrl() != null) {
      return ConditionEvaluationResult.enabled("using EDA_TEST_JDBC_URL");
    }
    if (TestDatabases.dockerAvailable()) {
      return ConditionEvaluationResult.enabled("using Testcontainers PostgreSQL");
    }
    return ConditionEvaluationResult.disabled(
        "no PostgreSQL: Docker unavailable and EDA_TEST_JDBC_URL unset");
  }
}
