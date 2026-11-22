package com.edacommerce.edacommon.it;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.edacommerce.edacommon.config.EdaProperties;
import com.edacommerce.edacommon.http.Caller;
import com.edacommerce.edacommon.idempotency.IdempotencyFilter;
import com.edacommerce.edacommon.idempotency.IdempotencyStore;
import com.edacommerce.edacommon.testing.RequiresPostgres;
import java.time.Clock;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/** ADR-0012 semantics against a real database. */
@RequiresPostgres
class IdempotencyFilterIT {
  final DbFixture db = new DbFixture();
  static volatile CountDownLatch hold;

  @RestController
  static class Orders {
    final JdbcTemplate jdbc;

    Orders(JdbcTemplate jdbc) {
      this.jdbc = jdbc;
    }

    @PostMapping("/checkouts")
    ResponseEntity<Map<String, String>> submit(@RequestBody Map<String, Object> body) throws InterruptedException {
      CountDownLatch h = hold;
      if (h != null) {
        h.await(5, TimeUnit.SECONDS);
      }
      if (Boolean.TRUE.equals(body.get("fail"))) {
        return ResponseEntity.unprocessableEntity().build();
      }
      String orderId = UUID.randomUUID().toString();
      jdbc.update("INSERT INTO effect (id, n) VALUES (?, 1)", orderId);
      return ResponseEntity.status(HttpStatus.ACCEPTED)
          .header("Location", "/orders/" + orderId)
          .body(Map.of("orderId", orderId));
    }
  }

  final MockMvc mvc =
      MockMvcBuilders.standaloneSetup(new Orders(db.jdbc))
          .addFilters(
              new IdempotencyFilter(
                  new IdempotencyStore(db.jdbc), db.tx, new Caller(new EdaProperties()), List.of("/checkouts"),
                  Duration.ofHours(24), Clock.systemUTC()))
          .build();

  @AfterEach
  void close() {
    hold = null;
    db.close();
  }

  MvcResult send(String key, String body) throws Exception {
    return mvc.perform(post("/checkouts").header("Idempotency-Key", key).contentType(MediaType.APPLICATION_JSON).content(body))
        .andReturn();
  }

  @Test
  void sameKeyAndBodyReplaysTheSameResponse() throws Exception {
    MvcResult first = send("k1", "{\"cartId\":\"c1\",\"n\":1}");
    assertThat(first.getResponse().getStatus()).isEqualTo(202);
    MvcResult again = send("k1", "{ \"n\": 1, \"cartId\": \"c1\" }");
    assertThat(again.getResponse().getStatus()).isEqualTo(202);
    assertThat(again.getResponse().getHeader("Idempotent-Replayed")).isEqualTo("true");
    assertThat(again.getResponse().getContentAsString()).isEqualTo(first.getResponse().getContentAsString());
    assertThat(again.getResponse().getHeader("Location")).isEqualTo(first.getResponse().getHeader("Location"));
    assertThat(db.count("SELECT count(*) FROM effect")).isEqualTo(1);
    assertThat(db.count("SELECT count(*) FROM idempotency_key WHERE status = 'COMPLETED'")).isEqualTo(1);
  }

  @Test
  void sameKeyDifferentBodyIs422() throws Exception {
    send("k2", "{\"cartId\":\"c1\"}");
    mvc.perform(post("/checkouts").header("Idempotency-Key", "k2").contentType(MediaType.APPLICATION_JSON).content("{\"cartId\":\"c2\"}"))
        .andExpect(status().isUnprocessableEntity())
        .andExpect(jsonPath("$.type").value("https://errors.edacommerce.example/idempotency-key-reused"));
  }

  @Test
  void missingKeyIs400() throws Exception {
    mvc.perform(post("/checkouts").contentType(MediaType.APPLICATION_JSON).content("{}"))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.errors[0].field").value("Idempotency-Key"));
  }

  @Test
  void concurrentSameKeyIs409ThenReplays() throws Exception {
    hold = new CountDownLatch(1);
    ExecutorService pool = Executors.newSingleThreadExecutor();
    Future<MvcResult> first = pool.submit(() -> send("k3", "{\"cartId\":\"c1\"}"));
    Thread.sleep(300);
    MvcResult concurrent = send("k3", "{\"cartId\":\"c1\"}");
    assertThat(concurrent.getResponse().getStatus()).isEqualTo(409);
    assertThat(concurrent.getResponse().getHeader("Retry-After")).isEqualTo("1");
    hold.countDown();
    assertThat(first.get(10, TimeUnit.SECONDS).getResponse().getStatus()).isEqualTo(202);
    hold = null;
    assertThat(send("k3", "{\"cartId\":\"c1\"}").getResponse().getHeader("Idempotent-Replayed")).isEqualTo("true");
    pool.shutdown();
    assertThat(db.count("SELECT count(*) FROM effect")).isEqualTo(1);
  }

  @Test
  void failedRequestsStoreNothingSoTheClientCanRetry() throws Exception {
    mvc.perform(post("/checkouts").header("Idempotency-Key", "k4").contentType(MediaType.APPLICATION_JSON).content("{\"fail\":true}"))
        .andExpect(status().isUnprocessableEntity())
        .andExpect(header().doesNotExist("Idempotent-Replayed"));
    assertThat(db.count("SELECT count(*) FROM idempotency_key")).isZero();
  }
}
