package com.edacommerce.inventory.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.edacommerce.common.StockLine;
import com.edacommerce.edacommon.envelope.EdaHeaders;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.ids.Ids;
import com.edacommerce.edacommon.metrics.EdaMetrics.Outcome;
import com.edacommerce.edacommon.testing.EdaServiceTest;
import com.edacommerce.edacommon.testing.MessageDriver;
import com.edacommerce.edacommon.testing.MutableClock;
import com.edacommerce.edacommon.testing.OpenApiContract;
import com.edacommerce.edacommon.testing.SharedTables;
import com.edacommerce.inventory.CommitReservation;
import com.edacommerce.inventory.ItemsRestocked;
import com.edacommerce.inventory.ReleaseReservation;
import com.edacommerce.inventory.ReservationCommitted;
import com.edacommerce.inventory.ReservationExpired;
import com.edacommerce.inventory.ReservationReleased;
import com.edacommerce.inventory.ReserveStock;
import com.edacommerce.inventory.RestockItems;
import com.edacommerce.inventory.StockLevelChanged;
import com.edacommerce.inventory.StockReservationRejected;
import com.edacommerce.inventory.StockReserved;
import com.edacommerce.inventory.application.InventoryUseCases;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import javax.sql.DataSource;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;

/** Layer 3 for inventory-svc: real Spring context, Flyway, PostgreSQL; handlers driven directly. */
@EdaServiceTest
class InventoryServiceIT {
  @Autowired ApplicationContext ctx;
  @Autowired MockMvc mvc;
  @Autowired JdbcTemplate jdbc;
  @Autowired DataSource dataSource;
  @Autowired MutableClock clock;
  @Autowired InventoryUseCases useCases;
  MessageDriver driver;
  String sku;

  @BeforeEach
  void setUp() throws Exception {
    driver = new MessageDriver(ctx);
    sku = "SKU-" + Ids.newId().substring(24);
    mvc.perform(put("/admin/stock/" + sku).contentType(MediaType.APPLICATION_JSON).content("{\"onHand\": 3}"))
        .andExpect(status().isOk())
        .andExpect(OpenApiContract.validResponse("admin.yaml"));
  }

  @AfterEach
  void resetClock() {
    clock.reset();
  }

  ReserveStock reserve(String orderId, String reservationId, int qty, int ttlSeconds) {
    return ReserveStock.newBuilder().setEnvelope(Envelopes.placeholder()).setOrderId(orderId).setReservationId(reservationId)
        .setLines(List.of(new StockLine(sku, qty))).setTtlSeconds(ttlSeconds).build();
  }

  int reserved() {
    return jdbc.queryForObject("SELECT reserved FROM stock WHERE sku = ?", Integer.class, sku);
  }

  int onHand() {
    return jdbc.queryForObject("SELECT on_hand FROM stock WHERE sku = ?", Integer.class, sku);
  }

  @Test
  void sharedTablesMatchTheContract() {
    SharedTables.assertMatchesContract(dataSource);
  }

  @Test
  void adminSeedPublishesAStockLevelSnapshot() {
    List<StockLevelChanged> levels = driver.published(StockLevelChanged.class, sku);
    assertThat(levels).hasSize(1);
    assertThat(levels.get(0).getAvailable()).isEqualTo(3);
    assertThat(levels.get(0).getEnvelope().getPartitionKey()).isEqualTo(sku);
  }

  @Test
  void reserveStockRepliesWithEnvelopeAndUpdatesStock() {
    String orderId = Ids.newId();
    MessageDriver.Delivery d = driver.deliver("inventory.commands.v1", orderId, reserve(orderId, "r-" + orderId, 2, 900));
    assertThat(d.outcome()).isEqualTo(Outcome.SUCCESS);
    assertThat(reserved()).isEqualTo(2);

    MessageDriver.Published reply = driver.publishedFor(orderId).get(0);
    assertThat(reply.topic()).isEqualTo("inventory.events.v1");
    assertThat(reply.record()).isInstanceOf(StockReserved.class);
    assertThat(reply.envelope().getType()).isEqualTo("com.edacommerce.inventory.StockReserved");
    assertThat(reply.envelope().getProducer()).isEqualTo("inventory-svc");
    assertThat(reply.envelope().getPartitionKey()).isEqualTo(orderId);
    assertThat(reply.envelope().getCausationId()).isEqualTo(d.eventId());
    assertThat(reply.envelope().getCorrelationId()).isEqualTo(orderId);
    assertThat(driver.published(StockLevelChanged.class, sku)).last().satisfies(l -> assertThat(l.getAvailable()).isEqualTo(1));
  }

  @Test
  void theSameMessageTwiceHasOneEffectAndOneReply() {
    String orderId = Ids.newId();
    MessageDriver.Delivery d = driver.deliver("inventory.commands.v1", orderId, reserve(orderId, "r-" + orderId, 1, 900));
    assertThat(driver.redeliver(d).outcome()).isEqualTo(Outcome.DUPLICATE);
    assertThat(reserved()).isEqualTo(1);
    assertThat(driver.published(StockReserved.class, orderId)).hasSize(1);
  }

  @Test
  void aResentCommandReEmitsTheOriginalReplyWithoutRepeatingTheEffect() {
    String orderId = Ids.newId();
    driver.deliver("inventory.commands.v1", orderId, reserve(orderId, "r-" + orderId, 1, 900));
    driver.deliver("inventory.commands.v1", orderId, reserve(orderId, "r-" + orderId, 1, 900));
    assertThat(reserved()).isEqualTo(1);
    List<StockReserved> replies = driver.published(StockReserved.class, orderId);
    assertThat(replies).hasSize(2);
    assertThat(replies.get(1).getExpiresAt()).isEqualTo(replies.get(0).getExpiresAt());
  }

  @Test
  void twoConcurrentReservationsForTheLastUnitExactlyOneWins() throws Exception {
    useCases.setStock(sku, 1);
    String o1 = Ids.newId();
    String o2 = Ids.newId();
    CountDownLatch go = new CountDownLatch(1);
    ExecutorService pool = Executors.newFixedThreadPool(2);
    List<Callable<Object>> calls = List.of(
        () -> { go.await(); return driver.deliver("inventory.commands.v1", o1, reserve(o1, "r-" + o1, 1, 900)).outcome(); },
        () -> { go.await(); return driver.deliver("inventory.commands.v1", o2, reserve(o2, "r-" + o2, 1, 900)).outcome(); });
    List<Future<Object>> futures = calls.stream().map(pool::submit).toList();
    go.countDown();
    for (Future<Object> f : futures) {
      assertThat(f.get()).isEqualTo(Outcome.SUCCESS);
    }
    pool.shutdown();
    int won = driver.published(StockReserved.class, o1).size() + driver.published(StockReserved.class, o2).size();
    int lost = driver.published(StockReservationRejected.class, o1).size() + driver.published(StockReservationRejected.class, o2).size();
    assertThat(won).isEqualTo(1);
    assertThat(lost).isEqualTo(1);
    assertThat(reserved()).isEqualTo(1);
  }

  @Test
  void ttlExpiryEmitsReservationExpiredRestoresStockAndALateCommitIsAnsweredExpired() {
    String orderId = Ids.newId();
    driver.deliver("inventory.commands.v1", orderId, reserve(orderId, "r-" + orderId, 2, 1));
    assertThat(reserved()).isEqualTo(2);
    clock.advance(Duration.ofSeconds(2));
    assertThat(useCases.expireDue(100)).isGreaterThanOrEqualTo(1);
    assertThat(reserved()).isZero();
    assertThat(driver.published(ReservationExpired.class, orderId)).hasSize(1);
    assertThat(driver.published(StockLevelChanged.class, sku)).last().satisfies(l -> assertThat(l.getAvailable()).isEqualTo(3));

    driver.deliver("inventory.commands.v1", orderId, CommitReservation.newBuilder().setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId).setReservationId("r-" + orderId).build());
    assertThat(driver.published(ReservationExpired.class, orderId)).hasSize(2);
    assertThat(driver.published(ReservationCommitted.class, orderId)).isEmpty();
  }

  @Test
  void commitAllocatesAndReleaseReturnsTheAllocationOnce() {
    String orderId = Ids.newId();
    driver.deliver("inventory.commands.v1", orderId, reserve(orderId, "r-" + orderId, 2, 900));
    driver.deliver("inventory.commands.v1", orderId, CommitReservation.newBuilder().setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId).setReservationId("r-" + orderId).build());
    assertThat(onHand()).isEqualTo(1);
    assertThat(reserved()).isZero();
    ReleaseReservation release = ReleaseReservation.newBuilder().setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId).setReservationId("r-" + orderId).setReason("fulfilment failed").build();
    driver.deliver("inventory.commands.v1", orderId, release);
    driver.deliver("inventory.commands.v1", orderId, ReleaseReservation.newBuilder(release).build());
    assertThat(onHand()).isEqualTo(3);
    assertThat(driver.published(ReservationReleased.class, orderId)).hasSize(2);
  }

  @Test
  void restockIsIdempotentOnRestockId() {
    String orderId = Ids.newId();
    RestockItems cmd = RestockItems.newBuilder().setEnvelope(Envelopes.placeholder()).setOrderId(orderId).setReturnId("ret")
        .setRestockId("rs-" + orderId).setLines(List.of(new StockLine(sku, 2))).build();
    driver.deliver("inventory.commands.v1", orderId, cmd);
    driver.deliver("inventory.commands.v1", orderId, RestockItems.newBuilder(cmd).build());
    assertThat(onHand()).isEqualTo(5);
    assertThat(driver.published(ItemsRestocked.class, orderId)).hasSize(2);
  }

  @Test
  void unknownTypesOnTheCommandTopicAreIgnored() {
    ConsumerRecord<String, byte[]> r = new ConsumerRecord<>("inventory.commands.v1", 0, 0L, "o", new byte[] {1});
    r.headers().add(EdaHeaders.CE_ID, Ids.newId().getBytes(StandardCharsets.UTF_8));
    r.headers().add(EdaHeaders.CE_TYPE, "com.edacommerce.inventory.SomethingNew".getBytes(StandardCharsets.UTF_8));
    assertThat(driver.processor().process(r)).isEqualTo(Outcome.IGNORED);
  }
}
