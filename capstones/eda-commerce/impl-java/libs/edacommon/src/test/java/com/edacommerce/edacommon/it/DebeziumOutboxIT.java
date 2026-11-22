package com.edacommerce.edacommon.it;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.edacommon.serde.AvroSerde;
import com.edacommerce.edacommon.testing.Contracts;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.edacommon.testing.InMemorySchemaRegistry;
import com.edacommerce.order.OrderPlaced;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.zaxxer.hikari.HikariDataSource;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.time.Clock;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.common.serialization.ByteArrayDeserializer;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.Network;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.containers.wait.strategy.Wait;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.kafka.KafkaContainer;

/**
 * Checklist: "one test per build runs the Debezium connector in a container and observes an outbox
 * row arrive on its topic with the expected headers". Uses the repository's own connector config
 * (infra/connect/connectors/order-svc-outbox.json) with only the connection settings replaced.
 */
@Testcontainers(disabledWithoutDocker = true)
class DebeziumOutboxIT {
  static final Network NET = Network.newNetwork();

  @Container
  static final KafkaContainer KAFKA =
      new KafkaContainer("apache/kafka:3.9.1").withNetwork(NET).withNetworkAliases("kafka")
          .withListener("kafka:19092");

  @Container
  static final PostgreSQLContainer<?> PG =
      new PostgreSQLContainer<>("postgres:16-alpine").withNetwork(NET).withNetworkAliases("postgres")
          .withDatabaseName("order_db").withCommand("postgres", "-c", "wal_level=logical");

  @Container
  static final GenericContainer<?> CONNECT =
      new GenericContainer<>("quay.io/debezium/connect:3.0.7.Final")
          .withNetwork(NET)
          .dependsOn(KAFKA, PG)
          .withEnv("BOOTSTRAP_SERVERS", "kafka:19092")
          .withEnv("GROUP_ID", "connect-it")
          .withEnv("CONFIG_STORAGE_TOPIC", "connect_configs")
          .withEnv("OFFSET_STORAGE_TOPIC", "connect_offsets")
          .withEnv("STATUS_STORAGE_TOPIC", "connect_statuses")
          .withExposedPorts(8083)
          .waitingFor(Wait.forHttp("/connectors").forPort(8083).withStartupTimeout(Duration.ofMinutes(3)));

  @Test
  void anOutboxRowArrivesOnItsTopicWithTheCloudEventsHeaders() throws Exception {
    HikariDataSource ds = new HikariDataSource();
    ds.setJdbcUrl(PG.getJdbcUrl());
    ds.setUsername(PG.getUsername());
    ds.setPassword(PG.getPassword());
    JdbcTemplate jdbc = new JdbcTemplate(ds);
    jdbc.execute(Contracts.commonTablesSql());

    ObjectMapper json = new ObjectMapper();
    ObjectNode connector = (ObjectNode) json.readTree(
        Files.readString(Contracts.dir().resolve("../infra/connect/connectors/order-svc-outbox.json")));
    ObjectNode config = (ObjectNode) connector.get("config");
    config.put("database.user", PG.getUsername());
    config.put("database.password", PG.getPassword());
    HttpResponse<String> created = HttpClient.newHttpClient().send(
        HttpRequest.newBuilder(URI.create("http://" + CONNECT.getHost() + ":" + CONNECT.getMappedPort(8083) + "/connectors"))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(connector.toString()))
            .build(),
        HttpResponse.BodyHandlers.ofString());
    assertThat(created.statusCode()).as(created.body()).isIn(200, 201);

    AvroSerde serde = new AvroSerde(new InMemorySchemaRegistry());
    OutboxWriter outbox = new OutboxWriter(jdbc, serde, Clock.systemUTC(), IdGenerator.uuidV7(), "order-svc");
    TransactionTemplate tx = new TransactionTemplate(new DataSourceTransactionManager(ds));
    OrderPlaced e = GoldenFixtures.decode(OrderPlaced.class);
    String eventId = tx.execute(s -> outbox.append(
        OutgoingMessage.of("order.events.v1", e.getOrderId(), e, "Order", e.getOrderId(), 1), new Causation(e.getOrderId(), "cause-1")));
    byte[] payload = jdbc.queryForObject("SELECT payload FROM outbox", byte[].class);

    Map<String, Object> props = Map.of(
        ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, KAFKA.getBootstrapServers(),
        ConsumerConfig.GROUP_ID_CONFIG, "debezium-it",
        ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
    List<ConsumerRecord<String, byte[]>> got = new ArrayList<>();
    try (KafkaConsumer<String, byte[]> c = new KafkaConsumer<>(props, new StringDeserializer(), new ByteArrayDeserializer())) {
      c.subscribe(List.of("order.events.v1"));
      await().atMost(Duration.ofMinutes(2)).until(() -> {
        c.poll(Duration.ofMillis(500)).forEach(got::add);
        return !got.isEmpty();
      });
    }
    ConsumerRecord<String, byte[]> r = got.get(0);
    assertThat(r.key()).isEqualTo(e.getOrderId());
    assertThat(r.value()).isEqualTo(payload);
    assertThat(header(r, "ce_id")).isEqualTo(eventId);
    assertThat(header(r, "id")).isEqualTo(eventId);
    assertThat(header(r, "ce_type")).isEqualTo("com.edacommerce.order.OrderPlaced");
    assertThat(header(r, "ce_source")).isEqualTo("order-svc");
    assertThat(header(r, "ce_specversion")).isEqualTo("1.0");
    assertThat(header(r, "causation_id")).isEqualTo("cause-1");
    assertThat(header(r, "ce_time")).isNotBlank();
    ds.close();
  }

  static String header(ConsumerRecord<String, byte[]> r, String name) {
    var h = r.headers().lastHeader(name);
    return h == null || h.value() == null ? null : new String(h.value(), StandardCharsets.UTF_8);
  }
}
