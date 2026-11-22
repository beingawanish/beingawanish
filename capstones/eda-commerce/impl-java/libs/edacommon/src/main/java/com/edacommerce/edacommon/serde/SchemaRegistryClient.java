package com.edacommerce.edacommon.serde;

import org.apache.avro.Schema;

/**
 * The two Schema Registry calls a service needs (ADR-0004). Services never register schemas
 * ({@code auto.register.schemas=false}); {@code make schemas} does. Implementations cache: a
 * registry outage then only hurts cold starts and new schemas ({@code chaos-registry} drill).
 */
public interface SchemaRegistryClient {

  /**
   * The id of {@code schema} under {@code subject}, looked up with {@code normalize=true} so that a
   * schema differing only in whitespace or property order resolves to the same id.
   *
   * @throws SchemaNotRegisteredException if the registry does not know this schema under the subject
   */
  int lookupId(String subject, Schema schema);

  /** The writer schema for an id from a message's wire-format header. */
  Schema schemaById(int id);

  /** True once the registry answered at least one call; used by readiness. */
  boolean isWarm();

  /** A cheap call that makes the client warm if the registry answers; false otherwise. */
  boolean ping();
}
