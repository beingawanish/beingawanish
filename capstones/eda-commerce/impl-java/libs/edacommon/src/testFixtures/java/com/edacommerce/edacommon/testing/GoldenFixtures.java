package com.edacommerce.edacommon.testing;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.UncheckedIOException;
import org.apache.avro.Schema;
import org.apache.avro.generic.GenericDatumReader;
import org.apache.avro.generic.GenericDatumWriter;
import org.apache.avro.io.BinaryEncoder;
import org.apache.avro.io.DecoderFactory;
import org.apache.avro.io.EncoderFactory;
import org.apache.avro.specific.SpecificData;
import org.apache.avro.specific.SpecificDatumReader;
import org.apache.avro.specific.SpecificDatumWriter;
import org.apache.avro.specific.SpecificRecord;

/**
 * Golden-message checks (ADR-0014 layer 2): every {@code .bin} decodes to its {@code .json}, and
 * encoding the {@code .json} reproduces the bytes exactly. The {@code .bin} files are raw Avro
 * (schemaless, no wire-format header).
 */
public final class GoldenFixtures {
  private GoldenFixtures() {}

  private static final ObjectMapper JSON = new ObjectMapper();

  /** Generic path: decode with the bundled schema, compare JSON, re-encode JSON, compare bytes. */
  public static void assertGenericRoundTrip(String fullName) {
    Schema schema = Contracts.bundledSchema(fullName);
    byte[] bin = Contracts.exampleBin(fullName);
    JsonNode expected = readJson(Contracts.exampleJson(fullName));
    try {
      Object decoded =
          new GenericDatumReader<>(schema).read(null, DecoderFactory.get().binaryDecoder(bin, null));
      assertThat(reparse(AvroJson.toPlain(decoded, schema))).as(fullName + " decodes to its .json").isEqualTo(expected);
      ByteArrayOutputStream out = new ByteArrayOutputStream();
      BinaryEncoder enc = EncoderFactory.get().binaryEncoder(out, null);
      new GenericDatumWriter<>(schema).write(AvroJson.fromPlain(expected, schema), enc);
      enc.flush();
      assertThat(out.toByteArray()).as(fullName + " .json encodes to its .bin").isEqualTo(bin);
    } catch (IOException e) {
      throw new UncheckedIOException(e);
    }
  }

  /** Decodes a golden {@code .bin} into the generated class (with Instant conversions). */
  public static <T extends SpecificRecord> T decode(Class<T> type) {
    SpecificData model = SpecificData.getForClass(type);
    Schema schema = model.getSchema(type);
    byte[] bin = Contracts.exampleBin(schema.getFullName());
    try {
      return new SpecificDatumReader<T>(schema, schema, model)
          .read(null, DecoderFactory.get().binaryDecoder(bin, null));
    } catch (IOException e) {
      throw new UncheckedIOException(e);
    }
  }

  /** Specific path: decode into the generated class and re-encode byte for byte; check the JSON. */
  public static <T extends SpecificRecord> T assertSpecificRoundTrip(Class<T> type) {
    T record = decode(type);
    Schema schema = record.getSchema();
    byte[] bin = Contracts.exampleBin(schema.getFullName());
    assertThat(encode(record)).as(schema.getFullName() + " re-encodes byte for byte").isEqualTo(bin);
    try {
      Object generic =
          new GenericDatumReader<>(schema).read(null, DecoderFactory.get().binaryDecoder(encode(record), null));
      assertThat(reparse(AvroJson.toPlain(generic, schema)))
          .isEqualTo(readJson(Contracts.exampleJson(schema.getFullName())));
    } catch (IOException e) {
      throw new UncheckedIOException(e);
    }
    return record;
  }

  /** Raw Avro (no wire header) of a specific record. */
  public static byte[] encode(SpecificRecord record) {
    try {
      ByteArrayOutputStream out = new ByteArrayOutputStream();
      BinaryEncoder enc = EncoderFactory.get().binaryEncoder(out, null);
      new SpecificDatumWriter<SpecificRecord>(record.getSchema(), SpecificData.getForSchema(record.getSchema()))
          .write(record, enc);
      enc.flush();
      return out.toByteArray();
    } catch (IOException e) {
      throw new UncheckedIOException(e);
    }
  }

  /**
   * A produced record is valid against the bundled (registered) schema: it encodes with the generated
   * schema and decodes with the bundled one, and the two schemas are the same contract.
   */
  public static void assertValidAgainstBundled(SpecificRecord record) {
    Schema bundled = Contracts.bundledSchema(record.getSchema().getFullName());
    assertThat(org.apache.avro.SchemaNormalization.parsingFingerprint64(record.getSchema()))
        .as("generated class schema equals bundled schema")
        .isEqualTo(org.apache.avro.SchemaNormalization.parsingFingerprint64(bundled));
    assertThat(GenericData.get().validate(bundled, toGeneric(record, bundled))).isTrue();
  }

  private static Object toGeneric(SpecificRecord record, Schema bundled) {
    try {
      return new GenericDatumReader<>(bundled).read(null, DecoderFactory.get().binaryDecoder(encode(record), null));
    } catch (IOException e) {
      throw new UncheckedIOException(e);
    }
  }

  /** Numbers compare by value: re-parse so int/long node types match what Jackson reads. */
  private static JsonNode reparse(JsonNode node) {
    return readJson(node.toString());
  }

  private static JsonNode readJson(String json) {
    try {
      return JSON.readTree(json);
    } catch (IOException e) {
      throw new UncheckedIOException(e);
    }
  }

  private static final class GenericData {
    private GenericData() {}

    static org.apache.avro.generic.GenericData get() {
      return org.apache.avro.generic.GenericData.get();
    }
  }
}
