package com.edacommerce.edacommon.testing;

import com.edacommerce.edacommon.serde.SchemaNotRegisteredException;
import com.edacommerce.edacommon.serde.SchemaRegistryClient;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.avro.Schema;
import org.apache.avro.SchemaNormalization;

/**
 * Schema Registry stand-in for tests without a registry container. Behaves like a registry into
 * which {@code make schemas} registered every bundled schema: a lookup succeeds for any subject whose
 * record name is a bundled contract, ids are stable per schema. Unknown schemas are rejected, like
 * {@code auto.register.schemas=false}.
 */
public class InMemorySchemaRegistry implements SchemaRegistryClient {
  private final AtomicInteger nextId = new AtomicInteger(1);
  private final Map<Long, Integer> idsByFingerprint = new ConcurrentHashMap<>();
  private final Map<Integer, Schema> schemasById = new ConcurrentHashMap<>();
  private final Map<String, Integer> subjects = new ConcurrentHashMap<>();

  @Override
  public int lookupId(String subject, Schema schema) {
    if (!subject.endsWith("-" + schema.getFullName())) {
      throw new SchemaNotRegisteredException("subject does not follow TopicRecordNameStrategy: " + subject);
    }
    Schema bundled;
    try {
      bundled = Contracts.bundledSchema(schema.getFullName());
    } catch (RuntimeException e) {
      throw new SchemaNotRegisteredException("not a contract schema: " + schema.getFullName());
    }
    long fp = SchemaNormalization.parsingFingerprint64(bundled);
    if (fp != SchemaNormalization.parsingFingerprint64(schema)) {
      throw new SchemaNotRegisteredException("schema differs from the bundled contract: " + subject);
    }
    int id =
        idsByFingerprint.computeIfAbsent(
            fp,
            k -> {
              int n = nextId.getAndIncrement();
              schemasById.put(n, bundled);
              return n;
            });
    subjects.put(subject, id);
    return id;
  }

  @Override
  public Schema schemaById(int id) {
    Schema s = schemasById.get(id);
    if (s == null) {
      throw new SchemaNotRegisteredException("unknown schema id " + id);
    }
    return s;
  }

  @Override
  public boolean isWarm() {
    return true;
  }

  @Override
  public boolean ping() {
    return true;
  }

  public Map<String, Integer> subjects() {
    return Map.copyOf(subjects);
  }
}
