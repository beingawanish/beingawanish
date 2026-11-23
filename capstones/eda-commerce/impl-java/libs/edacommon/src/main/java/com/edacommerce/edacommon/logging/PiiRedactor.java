package com.edacommerce.edacommon.logging;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.apache.avro.Schema;
import org.apache.avro.generic.IndexedRecord;

/**
 * Renders an Avro record for logs with every field tagged {@code "pii": true} in the schema
 * replaced by {@value #REDACTED} (guide §6.4, ADR-0013). Use this whenever a record must be logged;
 * never log a record's {@code toString()}.
 */
public final class PiiRedactor {
  private PiiRedactor() {}

  public static final String REDACTED = "[REDACTED]";

  public static Map<String, Object> redact(IndexedRecord record) {
    Map<String, Object> out = new LinkedHashMap<>();
    for (Schema.Field field : record.getSchema().getFields()) {
      Object pii = field.getObjectProp("pii");
      Object value = record.get(field.pos());
      if (Boolean.TRUE.equals(pii)) {
        out.put(field.name(), value == null ? null : REDACTED);
      } else {
        out.put(field.name(), render(value));
      }
    }
    return out;
  }

  private static Object render(Object value) {
    if (value instanceof IndexedRecord nested) {
      return redact(nested);
    }
    if (value instanceof List<?> list) {
      List<Object> out = new ArrayList<>(list.size());
      for (Object item : list) {
        out.add(render(item));
      }
      return out;
    }
    return value == null ? null : value.toString();
  }
}
