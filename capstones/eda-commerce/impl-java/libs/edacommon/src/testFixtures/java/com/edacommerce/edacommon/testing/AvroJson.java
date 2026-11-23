package com.edacommerce.edacommon.testing;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.apache.avro.Schema;
import org.apache.avro.generic.GenericData;
import org.apache.avro.generic.GenericRecord;

/**
 * Converts between Avro generic data and the "plain JSON" form of {@code contracts/examples/*.json}
 * (what fastavro reads and writes: unions are unwrapped, timestamps are epoch millis, enums are
 * strings). Used by golden-fixture tests only.
 */
public final class AvroJson {
  private AvroJson() {}

  private static final JsonNodeFactory F = JsonNodeFactory.instance;

  public static Object fromPlain(JsonNode node, Schema schema) {
    switch (schema.getType()) {
      case UNION -> {
        if (node == null || node.isNull()) {
          return null;
        }
        for (Schema branch : schema.getTypes()) {
          if (branch.getType() != Schema.Type.NULL && fits(node, branch)) {
            return fromPlain(node, branch);
          }
        }
        throw new IllegalArgumentException("no union branch fits " + node);
      }
      case RECORD -> {
        GenericRecord r = new GenericData.Record(schema);
        for (Schema.Field f : schema.getFields()) {
          r.put(f.pos(), fromPlain(node.get(f.name()), f.schema()));
        }
        return r;
      }
      case ARRAY -> {
        List<Object> out = new ArrayList<>();
        for (JsonNode item : node) {
          out.add(fromPlain(item, schema.getElementType()));
        }
        return new GenericData.Array<>(schema, out);
      }
      case MAP -> {
        Map<String, Object> out = new LinkedHashMap<>();
        for (Iterator<Map.Entry<String, JsonNode>> it = node.properties().iterator();
            it.hasNext(); ) {
          Map.Entry<String, JsonNode> e = it.next();
          out.put(e.getKey(), fromPlain(e.getValue(), schema.getValueType()));
        }
        return out;
      }
      case ENUM -> {
        return new GenericData.EnumSymbol(schema, node.asText());
      }
      case STRING -> {
        return node.asText();
      }
      case INT -> {
        return node.asInt();
      }
      case LONG -> {
        return node.asLong();
      }
      case BOOLEAN -> {
        return node.asBoolean();
      }
      case DOUBLE -> {
        return node.asDouble();
      }
      case FLOAT -> {
        return (float) node.asDouble();
      }
      case BYTES -> {
        return ByteBuffer.wrap(
            node.asText().getBytes(java.nio.charset.StandardCharsets.ISO_8859_1));
      }
      case NULL -> {
        return null;
      }
      default -> throw new IllegalArgumentException("unsupported " + schema.getType());
    }
  }

  public static JsonNode toPlain(Object datum, Schema schema) {
    switch (schema.getType()) {
      case UNION -> {
        if (datum == null) {
          return F.nullNode();
        }
        int branch = GenericData.get().resolveUnion(schema, datum);
        return toPlain(datum, schema.getTypes().get(branch));
      }
      case RECORD -> {
        GenericRecord r = (GenericRecord) datum;
        ObjectNode o = F.objectNode();
        for (Schema.Field f : schema.getFields()) {
          o.set(f.name(), toPlain(r.get(f.pos()), f.schema()));
        }
        return o;
      }
      case ARRAY -> {
        ArrayNode a = F.arrayNode();
        for (Object item : (List<?>) datum) {
          a.add(toPlain(item, schema.getElementType()));
        }
        return a;
      }
      case MAP -> {
        ObjectNode o = F.objectNode();
        ((Map<?, ?>) datum)
            .forEach((k, v) -> o.set(k.toString(), toPlain(v, schema.getValueType())));
        return o;
      }
      case ENUM, STRING -> {
        return F.textNode(datum.toString());
      }
      case INT -> {
        return F.numberNode((Integer) datum);
      }
      case LONG -> {
        return F.numberNode((Long) datum);
      }
      case BOOLEAN -> {
        return F.booleanNode((Boolean) datum);
      }
      case DOUBLE -> {
        return F.numberNode((Double) datum);
      }
      case FLOAT -> {
        return F.numberNode((Float) datum);
      }
      case NULL -> {
        return F.nullNode();
      }
      default -> throw new IllegalArgumentException("unsupported " + schema.getType());
    }
  }

  private static boolean fits(JsonNode node, Schema s) {
    return switch (s.getType()) {
      case RECORD, MAP -> node.isObject();
      case ARRAY -> node.isArray();
      case STRING, ENUM, BYTES -> node.isTextual();
      case INT, LONG -> node.isIntegralNumber();
      case DOUBLE, FLOAT -> node.isNumber();
      case BOOLEAN -> node.isBoolean();
      default -> false;
    };
  }
}
