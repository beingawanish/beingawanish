package com.edacommerce.edacommon.kafka;

import com.edacommerce.edacommon.config.EdaProperties;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import org.apache.kafka.clients.CommonClientConfigs;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.CooperativeStickyAssignor;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.common.config.SslConfigs;
import org.apache.kafka.common.serialization.ByteArrayDeserializer;
import org.apache.kafka.common.serialization.ByteArraySerializer;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;

/**
 * Kafka client settings of guide §7.1, identical for every service. Keys are UTF-8 strings without
 * Avro (guide §5 rule 2); values stay raw bytes so the runtime can dispatch on {@code ce_type}
 * before deserialising and forward records without re-serialising. The Java client's default
 * partitioner is murmur2, the same as Kafka Connect's (guide §5 rule 1).
 */
public final class KafkaClients {
  private KafkaClients() {}

  public static Map<String, Object> common(EdaProperties.Kafka k) {
    Map<String, Object> m = new HashMap<>();
    m.put(CommonClientConfigs.BOOTSTRAP_SERVERS_CONFIG, k.getBootstrapServers());
    m.put(CommonClientConfigs.SECURITY_PROTOCOL_CONFIG, k.getSecurityProtocol());
    if ("SSL".equalsIgnoreCase(k.getSecurityProtocol())) {
      if (k.getSslCaLocation() != null) {
        m.put(SslConfigs.SSL_TRUSTSTORE_TYPE_CONFIG, "PEM");
        m.put(SslConfigs.SSL_TRUSTSTORE_LOCATION_CONFIG, k.getSslCaLocation());
      }
      if (k.getSslCertLocation() != null && k.getSslKeyLocation() != null) {
        m.put(SslConfigs.SSL_KEYSTORE_TYPE_CONFIG, "PEM");
        m.put(SslConfigs.SSL_KEYSTORE_CERTIFICATE_CHAIN_CONFIG, read(k.getSslCertLocation()));
        m.put(SslConfigs.SSL_KEYSTORE_KEY_CONFIG, read(k.getSslKeyLocation()));
      }
    }
    return m;
  }

  public static Map<String, Object> consumer(EdaProperties.Kafka k) {
    Map<String, Object> m = common(k);
    m.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
    m.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, ByteArrayDeserializer.class);
    m.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, false);
    m.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
    m.put(ConsumerConfig.ISOLATION_LEVEL_CONFIG, "read_committed");
    m.put(
        ConsumerConfig.PARTITION_ASSIGNMENT_STRATEGY_CONFIG,
        CooperativeStickyAssignor.class.getName());
    m.put(ConsumerConfig.SESSION_TIMEOUT_MS_CONFIG, 45_000);
    m.put(ConsumerConfig.MAX_POLL_INTERVAL_MS_CONFIG, 300_000);
    m.put(ConsumerConfig.MAX_POLL_RECORDS_CONFIG, 100);
    if (k.getGroupInstanceId() != null && !k.getGroupInstanceId().isBlank()) {
      // Static membership; Spring suffixes it per container thread so instances stay unique.
      m.put(ConsumerConfig.GROUP_INSTANCE_ID_CONFIG, k.getGroupInstanceId());
    }
    return m;
  }

  public static Map<String, Object> producer(EdaProperties.Kafka k) {
    Map<String, Object> m = common(k);
    m.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
    m.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, ByteArraySerializer.class);
    m.put(ProducerConfig.ACKS_CONFIG, "all");
    m.put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, true);
    m.put(ProducerConfig.COMPRESSION_TYPE_CONFIG, "zstd");
    m.put(ProducerConfig.LINGER_MS_CONFIG, 5);
    return m;
  }

  private static String read(String path) {
    try {
      return Files.readString(Path.of(path));
    } catch (IOException e) {
      throw new UncheckedIOException("cannot read " + path, e);
    }
  }
}
