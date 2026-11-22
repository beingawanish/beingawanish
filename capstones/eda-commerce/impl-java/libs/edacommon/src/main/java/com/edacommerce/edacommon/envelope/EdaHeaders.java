package com.edacommerce.edacommon.envelope;

/**
 * Kafka header names (architecture §8.3 and §8.1). Lower case, exactly as written: header names are
 * case-sensitive and the Python build reads the same strings (guide §5 rule 11).
 */
public final class EdaHeaders {
  private EdaHeaders() {}

  public static final String ID = "id";
  public static final String CE_ID = "ce_id";
  public static final String CE_TYPE = "ce_type";
  public static final String CE_SOURCE = "ce_source";
  public static final String CE_SPECVERSION = "ce_specversion";
  public static final String CE_TIME = "ce_time";
  public static final String CORRELATION_ID = "correlation_id";
  public static final String CAUSATION_ID = "causation_id";
  public static final String TRACEPARENT = "traceparent";
  public static final String TRACESTATE = "tracestate";

  public static final String X_RETRY_ATTEMPT = "x-retry-attempt";
  public static final String X_ORIGINAL_TOPIC = "x-original-topic";
  public static final String X_ORIGINAL_PARTITION = "x-original-partition";
  public static final String X_ORIGINAL_OFFSET = "x-original-offset";
  public static final String X_NOT_BEFORE = "x-not-before";
  public static final String X_ERROR_CLASS = "x-error-class";
  public static final String X_ERROR_MESSAGE = "x-error-message";
  public static final String X_FAILED_CONSUMER_GROUP = "x-failed-consumer-group";

  public static final String SPEC_VERSION = "1.0";

  public static boolean isRetryHeader(String name) {
    return name.startsWith("x-");
  }
}
