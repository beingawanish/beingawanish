package com.edacommerce.edacommon.errors;

/**
 * How the consumer runtime reacts to a failure (ADR-0007). Every adapter classifies the exceptions it
 * raises into exactly one of these; {@link ErrorClassifier} does it once for infrastructure exceptions.
 */
public enum ErrorClass {
  /** Clears in seconds (connection refused, deadlock, serialisation failure): retry in place. */
  TRANSIENT,
  /** Clears in minutes (dependency degraded, object not there yet): forward to the retry topics. */
  RETRY_LATER,
  /** Never clears by waiting (cannot deserialise, invariant violated): forward to the DLQ. */
  NON_RETRYABLE
}
