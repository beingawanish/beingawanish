package com.edacommerce.edacommon.testing;

import java.time.Duration;
import org.apache.kafka.clients.producer.MockProducer;
import org.apache.kafka.common.serialization.ByteArraySerializer;
import org.apache.kafka.common.serialization.StringSerializer;

/**
 * A MockProducer that survives KafkaTemplate's close-after-send, so one instance records every send
 * (with {@code MockProducerFactory}).
 */
public class KeepOpenMockProducer extends MockProducer<String, byte[]> {
  public KeepOpenMockProducer() {
    super(true, null, new StringSerializer(), new ByteArraySerializer());
  }

  public static KeepOpenMockProducer create() {
    return new KeepOpenMockProducer();
  }

  @Override
  public void close() {}

  @Override
  public void close(Duration timeout) {}
}
