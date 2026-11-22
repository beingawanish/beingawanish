package com.edacommerce.edacommon.serde;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.edacommerce.edacommon.errors.NonRetryableException;
import com.edacommerce.edacommon.testing.Contracts;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.edacommon.testing.InMemorySchemaRegistry;
import com.edacommerce.order.CancellationReason;
import com.edacommerce.order.OrderCancelled;
import com.edacommerce.payment.PaymentDeclined;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import org.apache.avro.Schema;
import org.apache.avro.generic.GenericData;
import org.apache.avro.generic.GenericDatumReader;
import org.apache.avro.generic.GenericDatumWriter;
import org.apache.avro.generic.GenericRecord;
import org.apache.avro.io.BinaryEncoder;
import org.apache.avro.io.DecoderFactory;
import org.apache.avro.io.EncoderFactory;
import org.junit.jupiter.api.Test;

class AvroSerdeTest {
  private final InMemorySchemaRegistry registry = new InMemorySchemaRegistry();
  private final AvroSerde serde = new AvroSerde(registry);

  @Test
  void serialisesInConfluentWireFormatWithTopicRecordNameSubject() {
    OrderCancelled record = GoldenFixtures.decode(OrderCancelled.class);
    byte[] bytes = serde.serialize("order.events.v1", record);

    assertThat(bytes[0]).isEqualTo((byte) 0);
    int id = ByteBuffer.wrap(bytes, 1, 4).getInt();
    assertThat(registry.subjects()).containsEntry("order.events.v1-com.edacommerce.order.OrderCancelled", id);
    byte[] avro = java.util.Arrays.copyOfRange(bytes, 5, bytes.length);
    assertThat(avro).isEqualTo(Contracts.exampleBin("com.edacommerce.order.OrderCancelled"));
    assertThat(serde.deserialize(bytes, OrderCancelled.class)).isEqualTo(record);
  }

  @Test
  void rejectsBytesWithoutTheWireHeader() {
    assertThatThrownBy(() -> serde.deserialize(new byte[] {1, 2, 3}, OrderCancelled.class))
        .isInstanceOf(NonRetryableException.class);
    byte[] raw = Contracts.exampleBin("com.edacommerce.order.OrderCancelled");
    assertThatThrownBy(() -> serde.deserialize(raw, OrderCancelled.class))
        .isInstanceOf(NonRetryableException.class);
  }

  @Test
  void unknownSchemaIdIsNonRetryable() {
    byte[] bytes = ByteBuffer.allocate(6).put((byte) 0).putInt(999).put((byte) 0).array();
    assertThatThrownBy(() -> serde.deserialize(bytes, OrderCancelled.class))
        .isInstanceOf(NonRetryableException.class);
  }

  @Test
  void anUnknownEnumSymbolFromANewerWriterDecodesToUnknown() throws Exception {
    // A newer producer adds a decline reason this reader does not know (FULL_TRANSITIVE evolution).
    ObjectMapper json = new ObjectMapper();
    ObjectNode newer = (ObjectNode) json.readTree(Contracts.bundledSchema("com.edacommerce.payment.PaymentDeclined").toString());
    for (var field : newer.withArray("fields")) {
      if (field.path("name").asText().equals("reason")) {
        ArrayNode symbols = ((ObjectNode) field.get("type")).withArray("symbols");
        symbols.insert(0, "CARD_EXPIRED");
      }
    }
    newer.withArray("fields").add(json.readTree("{\"name\":\"riskScore\",\"type\":[\"null\",\"int\"],\"default\":null}"));
    Schema writer = new Schema.Parser().parse(newer.toString());

    PaymentDeclined golden = GoldenFixtures.decode(PaymentDeclined.class);
    GenericRecord asOld =
        (GenericRecord)
            new GenericDatumReader<>(golden.getSchema(), writer)
                .read(null, DecoderFactory.get().binaryDecoder(GoldenFixtures.encode(golden), null));
    asOld.put("reason", new GenericData.EnumSymbol(writer.getField("reason").schema(), "CARD_EXPIRED"));
    asOld.put("riskScore", 7);
    ByteArrayOutputStream out = new ByteArrayOutputStream();
    out.write(0);
    out.writeBytes(ByteBuffer.allocate(4).putInt(42).array());
    BinaryEncoder enc = EncoderFactory.get().binaryEncoder(out, null);
    new GenericDatumWriter<GenericRecord>(writer).write(asOld, enc);
    enc.flush();

    SchemaRegistryClient newerRegistry =
        new SchemaRegistryClient() {
          @Override
          public int lookupId(String subject, Schema schema) {
            return 42;
          }

          @Override
          public Schema schemaById(int id) {
            return writer;
          }

          @Override
          public boolean isWarm() {
            return true;
          }

          @Override
          public boolean ping() {
            return true;
          }
        };
    PaymentDeclined read = new AvroSerde(newerRegistry).deserialize(out.toByteArray(), PaymentDeclined.class);
    assertThat(read.getReason()).isEqualTo(com.edacommerce.payment.DeclineReason.UNKNOWN);
    assertThat(read.getPaymentId()).isEqualTo(golden.getPaymentId());
  }

  @Test
  void enumsCarryUnknownAsDefault() {
    assertThat(CancellationReason.getClassSchema().getEnumDefault()).isEqualTo("UNKNOWN");
  }
}
