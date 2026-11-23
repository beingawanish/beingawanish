package com.edacommerce.edacommon.serde;

import com.edacommerce.edacommon.errors.NonRetryableException;

/**
 * The schema is not registered under the subject. A contract or deployment bug, not a transient.
 */
public class SchemaNotRegisteredException extends NonRetryableException {
  private static final long serialVersionUID = 1L;

  public SchemaNotRegisteredException(String message) {
    super(message);
  }
}
