package com.edacommerce.edacommon.serde;

import com.edacommerce.edacommon.errors.NonRetryableException;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import org.apache.avro.AvroRuntimeException;
import org.apache.avro.Schema;
import org.apache.avro.generic.GenericDatumReader;
import org.apache.avro.generic.GenericRecord;
import org.apache.avro.io.BinaryEncoder;
import org.apache.avro.io.DecoderFactory;
import org.apache.avro.io.EncoderFactory;
import org.apache.avro.specific.SpecificData;
import org.apache.avro.specific.SpecificDatumReader;
import org.apache.avro.specific.SpecificDatumWriter;
import org.apache.avro.specific.SpecificRecord;

/**
 * Avro values in the Confluent wire format: magic byte 0, 4-byte big-endian schema id, Avro binary
 * (ADR-0004, guide §5 rule 3). Subjects use TopicRecordNameStrategy: {@code <topic>-<full name>}.
 * Deserialisation always resolves the writer schema against the handler's reader schema (the
 * generated class), which is what {@code specific.avro.reader=true} does in the Confluent serde.
 */
public class AvroSerde {
  public static final byte MAGIC_BYTE = 0;

  private final SchemaRegistryClient registry;

  public AvroSerde(SchemaRegistryClient registry) {
    this.registry = registry;
  }

  public static String subject(String topic, Schema schema) {
    return topic + "-" + schema.getFullName();
  }

  public byte[] serialize(String topic, SpecificRecord record) {
    Schema schema = record.getSchema();
    int id = registry.lookupId(subject(topic, schema), schema);
    ByteArrayOutputStream out = new ByteArrayOutputStream(256);
    out.write(MAGIC_BYTE);
    out.writeBytes(ByteBuffer.allocate(4).putInt(id).array());
    try {
      BinaryEncoder encoder = EncoderFactory.get().directBinaryEncoder(out, null);
      new SpecificDatumWriter<SpecificRecord>(schema, SpecificData.getForSchema(schema))
          .write(record, encoder);
      encoder.flush();
    } catch (IOException | AvroRuntimeException e) {
      throw new NonRetryableException("cannot serialise " + schema.getFullName(), e);
    }
    return out.toByteArray();
  }

  public <T extends SpecificRecord> T deserialize(byte[] data, Class<T> type) {
    int id = schemaId(data);
    Schema writer = registry.schemaById(id);
    SpecificData model = SpecificData.getForClass(type);
    Schema reader = model.getSchema(type);
    try {
      SpecificDatumReader<T> datumReader = new SpecificDatumReader<>(writer, reader, model);
      return datumReader.read(null, DecoderFactory.get().binaryDecoder(data, 5, data.length - 5, null));
    } catch (IOException | AvroRuntimeException | ClassCastException e) {
      throw new NonRetryableException(
          "cannot deserialise schema id " + id + " as " + reader.getFullName(), e);
    }
  }

  /** Decode with the writer schema only; for tooling (DLQ peek), never for handlers. */
  public GenericRecord deserializeGeneric(byte[] data) {
    Schema writer = registry.schemaById(schemaId(data));
    try {
      return new GenericDatumReader<GenericRecord>(writer)
          .read(null, DecoderFactory.get().binaryDecoder(data, 5, data.length - 5, null));
    } catch (IOException | AvroRuntimeException e) {
      throw new NonRetryableException("cannot decode " + writer.getFullName(), e);
    }
  }

  public static int schemaId(byte[] data) {
    if (data == null || data.length < 5 || data[0] != MAGIC_BYTE) {
      throw new NonRetryableException("value is not in the Confluent wire format");
    }
    return ByteBuffer.wrap(data, 1, 4).getInt();
  }
}
