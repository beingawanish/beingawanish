package com.edacommerce.edacommon.it;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

import com.edacommerce.edacommon.config.EdaProperties;
import com.edacommerce.edacommon.consumer.ConsumerContainers;
import com.edacommerce.edacommon.consumer.DlqService;
import com.edacommerce.edacommon.consumer.FailureForwarder;
import com.edacommerce.edacommon.consumer.HandlerRegistry;
import com.edacommerce.edacommon.consumer.JitteredExponentialBackOff;
import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.consumer.RecordProcessor;
import com.edacommerce.edacommon.envelope.MessageContext;
import com.edacommerce.edacommon.errors.NonRetryableException;
import com.edacommerce.edacommon.errors.RetryLaterException;
import com.edacommerce.edacommon.errors.TransientException;
import com.edacommerce.edacommon.kafka.KafkaClients;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.inventory.CommitReservation;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.kafka.clients.admin.AdminClient;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.serialization.ByteArrayDeserializer;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.ConcurrentMessageListenerContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.kafka.KafkaContainer;

/**
 * Layer-3 checklist items for the consumer runtime on a real broker (skipped without Docker):
 * in-place retry of Transient, RetryLater to G.retry.10s with x-* headers and unchanged bytes,
 * NonRetryable to G.dlq, DLQ replay processed once, graceful shutdown finishing the in-flight
 * record.
 */
@Testcontainers(disabledWithoutDocker = true)
class ConsumerRuntimeKafkaIT {
  static final String GROUP = "it-svc";
  static final String TOPIC = "inventory.commands.v1";

  @Container static final KafkaContainer KAFKA = new KafkaContainer("apache/kafka:3.9.1");

  DbFixture db;
  final AtomicInteger calls = new AtomicInteger();
  volatile String mode = "ok";
  volatile int transientFailures;
  final List<ConcurrentMessageListenerContainer<String, byte[]>> containers = new ArrayList<>();
  KafkaTemplate<String, byte[]> template;
  DefaultKafkaConsumerFactory<String, byte[]> consumerFactory;

  final MessageHandler<CommitReservation> handler =
      new MessageHandler<>() {
        @Override
        public Class<CommitReservation> messageType() {
          return CommitReservation.class;
        }

        @Override
        public void handle(CommitReservation cmd, MessageContext ctx) {
          calls.incrementAndGet();
          switch (mode) {
            case "transient" -> {
              if (transientFailures-- > 0) {
                throw new TransientException("db failover");
              }
            }
            case "later" -> throw new RetryLaterException("dependency degraded");
            case "poison" -> throw new NonRetryableException("invariant violated");
            case "slow" -> sleep(2000);
            default -> {}
          }
          db.jdbc.update(
              "INSERT INTO effect (id, n) VALUES (?, 1) ON CONFLICT (id) DO UPDATE SET n = effect.n + 1",
              ctx.eventId());
        }
      };

  @BeforeEach
  void setUp() throws Exception {
    db = new DbFixture();
    try (AdminClient admin =
        AdminClient.create(Map.of("bootstrap.servers", KAFKA.getBootstrapServers()))) {
      List<NewTopic> topics = new ArrayList<>();
      for (String t :
          List.of(
              TOPIC,
              GROUP + ".retry.10s",
              GROUP + ".retry.1m",
              GROUP + ".retry.10m",
              GROUP + ".dlq")) {
        topics.add(new NewTopic(t, 1, (short) 1));
      }
      admin
          .createTopics(topics)
          .values()
          .values()
          .forEach(
              f -> {
                try {
                  f.get();
                } catch (Exception ignored) {
                  // already exists from a previous test
                }
              });
    }
    EdaProperties.Kafka k = new EdaProperties.Kafka();
    k.setBootstrapServers(KAFKA.getBootstrapServers());
    template = new KafkaTemplate<>(new DefaultKafkaProducerFactory<>(KafkaClients.producer(k)));
    consumerFactory = new DefaultKafkaConsumerFactory<>(KafkaClients.consumer(k));
    RecordProcessor processor =
        new RecordProcessor(
            GROUP,
            new HandlerRegistry(List.of(handler)),
            db.inbox,
            db.serde,
            db.tx,
            db.tracing,
            db.metrics,
            db.clock);
    FailureForwarder forwarder = new FailureForwarder(template, GROUP, db.metrics, db.clock);
    containers.add(
        ConsumerContainers.main(
            consumerFactory,
            List.of(TOPIC),
            processor,
            ConsumerContainers.errorHandler(forwarder, JitteredExponentialBackOff.adr0007()),
            1,
            Duration.ofSeconds(10)));
    containers.add(
        ConsumerContainers.retry(
            consumerFactory,
            processor,
            ConsumerContainers.errorHandler(forwarder, JitteredExponentialBackOff.adr0007()),
            1,
            Duration.ofSeconds(10),
            db.clock));
    containers.forEach(ConcurrentMessageListenerContainer::start);
  }

  @AfterEach
  void tearDown() {
    containers.forEach(ConcurrentMessageListenerContainer::stop);
    db.close();
  }

  String send() throws Exception {
    String eventId = UUID.randomUUID().toString();
    byte[] value = db.serde.serialize(TOPIC, GoldenFixtures.decode(CommitReservation.class));
    ProducerRecord<String, byte[]> r = new ProducerRecord<>(TOPIC, "order-1", value);
    r.headers().add("ce_id", eventId.getBytes(StandardCharsets.UTF_8));
    r.headers()
        .add(
            "ce_type",
            "com.edacommerce.inventory.CommitReservation".getBytes(StandardCharsets.UTF_8));
    template.send(r).get();
    return eventId;
  }

  List<ConsumerRecord<String, byte[]>> read(String topic) {
    Map<String, Object> props =
        Map.of(
            ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG,
            KAFKA.getBootstrapServers(),
            ConsumerConfig.GROUP_ID_CONFIG,
            "reader-" + UUID.randomUUID(),
            ConsumerConfig.AUTO_OFFSET_RESET_CONFIG,
            "earliest");
    try (KafkaConsumer<String, byte[]> c =
        new KafkaConsumer<>(props, new StringDeserializer(), new ByteArrayDeserializer())) {
      c.subscribe(List.of(topic));
      List<ConsumerRecord<String, byte[]>> out = new ArrayList<>();
      long until = System.currentTimeMillis() + 5000;
      while (System.currentTimeMillis() < until) {
        c.poll(Duration.ofMillis(500)).forEach(out::add);
      }
      return out;
    }
  }

  int effects() {
    return db.count("SELECT coalesce(sum(n), 0) FROM effect");
  }

  @Test
  void transientFailuresRetryInPlaceAndSucceed() throws Exception {
    mode = "transient";
    transientFailures = 2;
    send();
    await().atMost(Duration.ofSeconds(30)).until(() -> effects() == 1);
    assertThat(calls.get()).isEqualTo(3);
    assertThat(read(GROUP + ".retry.10s")).isEmpty();
  }

  @Test
  void retryLaterLandsOnTheFirstRetryTopicWithHeadersAndRawBytes() throws Exception {
    mode = "later";
    String eventId = send();
    await().atMost(Duration.ofSeconds(30)).until(() -> !read(GROUP + ".retry.10s").isEmpty());
    ConsumerRecord<String, byte[]> r = read(GROUP + ".retry.10s").get(0);
    assertThat(new String(r.headers().lastHeader("ce_id").value(), StandardCharsets.UTF_8))
        .isEqualTo(eventId);
    for (String h :
        List.of(
            "x-retry-attempt",
            "x-original-topic",
            "x-original-partition",
            "x-original-offset",
            "x-not-before",
            "x-error-class",
            "x-error-message",
            "x-failed-consumer-group")) {
      assertThat(r.headers().lastHeader(h)).as(h).isNotNull();
    }
    assertThat(r.value())
        .isEqualTo(db.serde.serialize(TOPIC, GoldenFixtures.decode(CommitReservation.class)));
  }

  @Test
  void poisonGoesToTheDlqAndReplayProcessesItOnce() throws Exception {
    mode = "poison";
    String eventId = send();
    DlqService dlq = new DlqService(GROUP, consumerFactory, template, db.clock);
    await().atMost(Duration.ofSeconds(30)).until(() -> !dlq.peek(10).isEmpty());
    assertThat(dlq.peek(10).get(0).eventId()).isEqualTo(eventId);
    assertThat(dlq.peek(10).get(0).originalTopic()).isEqualTo(TOPIC);

    mode = "ok";
    assertThat(dlq.replay(new DlqService.ReplayRequest(100, null, null))).isEqualTo(1);
    await().atMost(Duration.ofSeconds(30)).until(() -> effects() == 1);
    assertThat(dlq.replay(new DlqService.ReplayRequest(100, null, null))).isZero();
  }

  @Test
  void gracefulShutdownFinishesTheInFlightRecord() throws Exception {
    mode = "slow";
    send();
    await().atMost(Duration.ofSeconds(30)).until(() -> calls.get() == 1);
    long start = System.nanoTime();
    containers.forEach(ConcurrentMessageListenerContainer::stop);
    assertThat(Duration.ofNanos(System.nanoTime() - start)).isLessThan(Duration.ofSeconds(10));
    assertThat(effects()).isEqualTo(1);
  }

  static void sleep(long ms) {
    try {
      Thread.sleep(ms);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
    }
  }
}
