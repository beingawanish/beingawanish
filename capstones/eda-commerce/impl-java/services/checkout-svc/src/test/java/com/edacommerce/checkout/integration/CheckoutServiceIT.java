package com.edacommerce.checkout.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.edacommerce.catalog.PriceChanged;
import com.edacommerce.catalog.ProductStatus;
import com.edacommerce.catalog.ProductUpserted;
import com.edacommerce.checkout.CheckoutSubmitted;
import com.edacommerce.common.Money;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.ids.Ids;
import com.edacommerce.edacommon.testing.EdaServiceTest;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.edacommon.testing.MessageDriver;
import com.edacommerce.edacommon.testing.OpenApiContract;
import com.edacommerce.edacommon.testing.SharedTables;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import javax.sql.DataSource;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

/**
 * checkout-svc checklist: idempotent submit, 422 on reuse and price mismatch, 409 on concurrency.
 */
@EdaServiceTest
class CheckoutServiceIT {
  @Autowired ApplicationContext ctx;
  @Autowired MockMvc mvc;
  @Autowired DataSource dataSource;
  final ObjectMapper json = new ObjectMapper();
  MessageDriver driver;
  String sku;
  String discontinued;

  @BeforeEach
  void seedCatalog() {
    driver = new MessageDriver(ctx);
    sku = "SKU-" + Ids.newId().substring(28);
    discontinued = sku + "-OLD";
    product(sku, ProductStatus.ACTIVE, 1);
    product(discontinued, ProductStatus.DISCONTINUED, 1);
    price(sku, 12999, 1);
    price(discontinued, 19900, 1);
  }

  void product(String s, ProductStatus status, long version) {
    ProductUpserted p =
        ProductUpserted.newBuilder(GoldenFixtures.decode(ProductUpserted.class))
            .setSku(s)
            .setStatus(status)
            .build();
    p.getEnvelope().setAggregateVersion(version);
    p.getEnvelope().setAggregateType("Product");
    driver.deliver("catalog.product.v1", s, p);
  }

  void price(String s, long minor, long version) {
    PriceChanged p =
        PriceChanged.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setSku(s)
            .setListPrice(new Money(minor, "EUR"))
            .setSalePrice(null)
            .setValidFrom(java.time.Instant.now())
            .build();
    p.getEnvelope().setAggregateType("Price");
    p.getEnvelope().setAggregateVersion(version);
    driver.deliver("catalog.price.v1", s, p);
  }

  String cart() throws Exception {
    MvcResult r =
        mvc.perform(
                post("/carts")
                    .header("Idempotency-Key", Ids.newId())
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{}"))
            .andExpect(status().isCreated())
            .andExpect(header().exists("ETag"))
            .andExpect(OpenApiContract.validResponse("checkout.yaml"))
            .andReturn();
    return json.readTree(r.getResponse().getContentAsString()).get("cartId").asText();
  }

  static String checkoutBody(String cartId, long expected) {
    return "{\"cartId\":\""
        + cartId
        + "\",\"shippingAddress\":{\"recipientName\":\"Jane Doe\",\"line1\":\"Invalidenstrasse 1\","
        + "\"city\":\"Berlin\",\"postalCode\":\"10115\",\"countryCode\":\"DE\"},\"contactEmail\":\"jane.doe@example.com\","
        + "\"shippingMethod\":\"STANDARD\",\"paymentMethodToken\":\"tok_visa_ok\",\"expectedTotal\":{\"amountMinor\":"
        + expected
        + ",\"currency\":\"EUR\"}}";
  }

  MvcResult checkout(String key, String body) throws Exception {
    return mvc.perform(
            post("/checkouts")
                .header("Idempotency-Key", key)
                .contentType(MediaType.APPLICATION_JSON)
                .content(body))
        .andReturn();
  }

  @Test
  void sharedTablesMatchTheContract() {
    SharedTables.assertMatchesContract(dataSource);
  }

  @Test
  void cartLifecycleWithEtagsAndCatalogRules() throws Exception {
    String cartId = cart();
    mvc.perform(
            put("/carts/" + cartId + "/items/" + sku)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"quantity\":2}"))
        .andExpect(status().isOk())
        .andExpect(header().string("ETag", "\"2\""))
        .andExpect(jsonPath("$.subtotal.amountMinor").value(25998))
        .andExpect(OpenApiContract.validResponse("checkout.yaml"));
    mvc.perform(
            put("/carts/" + cartId + "/items/" + sku)
                .header("If-Match", "\"1\"")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"quantity\":1}"))
        .andExpect(status().isPreconditionFailed());
    mvc.perform(
            put("/carts/" + cartId + "/items/" + discontinued)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"quantity\":1}"))
        .andExpect(status().isUnprocessableEntity())
        .andExpect(jsonPath("$.type").value("https://errors.edacommerce.example/discontinued-sku"));
    mvc.perform(get("/carts/" + cartId))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.lines.length()").value(1))
        .andExpect(OpenApiContract.validResponse("checkout.yaml"));
    // A price change propagates to the cart view.
    price(sku, 9999, 2);
    mvc.perform(get("/carts/" + cartId)).andExpect(jsonPath("$.subtotal.amountMinor").value(19998));
    price(sku, 11111, 1); // stale snapshot: dropped
    mvc.perform(get("/carts/" + cartId)).andExpect(jsonPath("$.subtotal.amountMinor").value(19998));
  }

  @Test
  void submitIsIdempotentAndEmitsCheckoutSubmitted() throws Exception {
    String cartId = cart();
    mvc.perform(
        put("/carts/" + cartId + "/items/" + sku)
            .contentType(MediaType.APPLICATION_JSON)
            .content("{\"quantity\":1}"));
    String key = Ids.newId();
    MvcResult first = checkout(key, checkoutBody(cartId, 12999));
    assertThat(first.getResponse().getStatus())
        .as(first.getResponse().getContentAsString())
        .isEqualTo(202);
    JsonNode accepted = json.readTree(first.getResponse().getContentAsString());
    String orderId = accepted.get("orderId").asText();
    assertThat(first.getResponse().getHeader("Location")).isEqualTo("/orders/" + orderId);
    mvc.perform(
            post("/checkouts")
                .header("Idempotency-Key", Ids.newId())
                .contentType(MediaType.APPLICATION_JSON)
                .content(checkoutBody(cartId, 12999)))
        .andExpect(status().isUnprocessableEntity())
        .andExpect(
            jsonPath("$.type")
                .value("https://errors.edacommerce.example/cart-already-checked-out"));

    MvcResult replay = checkout(key, checkoutBody(cartId, 12999));
    assertThat(replay.getResponse().getStatus()).isEqualTo(202);
    assertThat(replay.getResponse().getHeader("Idempotent-Replayed")).isEqualTo("true");
    assertThat(json.readTree(replay.getResponse().getContentAsString()).get("orderId").asText())
        .isEqualTo(orderId);
    assertThat(checkout(key, checkoutBody(cartId, 1)).getResponse().getStatus()).isEqualTo(422);

    List<MessageDriver.Published> events = driver.publishedFor(orderId);
    assertThat(events).hasSize(1);
    CheckoutSubmitted e = (CheckoutSubmitted) events.get(0).record();
    assertThat(events.get(0).topic()).isEqualTo("checkout.events.v1");
    assertThat(e.getEnvelope().getAggregateId()).isEqualTo(accepted.get("checkoutId").asText());
    assertThat(e.getEnvelope().getPartitionKey()).isEqualTo(orderId);
    assertThat(e.getEnvelope().getCorrelationId()).isEqualTo(orderId);
    assertThat(e.getEnvelope().getCausationId()).isNull();
    assertThat(e.getTotal().getAmountMinor()).isEqualTo(12999L);
    assertThat(e.getLines()).singleElement().satisfies(l -> assertThat(l.getSku()).isEqualTo(sku));
    GoldenFixtures.assertValidAgainstBundled(e);
  }

  @Test
  void priceMismatchIs422() throws Exception {
    String cartId = cart();
    mvc.perform(
        put("/carts/" + cartId + "/items/" + sku)
            .contentType(MediaType.APPLICATION_JSON)
            .content("{\"quantity\":1}"));
    mvc.perform(
            post("/checkouts")
                .header("Idempotency-Key", Ids.newId())
                .contentType(MediaType.APPLICATION_JSON)
                .content(checkoutBody(cartId, 100)))
        .andExpect(status().isUnprocessableEntity())
        .andExpect(jsonPath("$.type").value("https://errors.edacommerce.example/price-mismatch"));
    mvc.perform(
            post("/checkouts")
                .header("Idempotency-Key", Ids.newId())
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"cartId\":\"x\"}"))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.errors").isArray());
  }

  @Test
  void concurrentSameKeyIs409() throws Exception {
    String cartId = cart();
    mvc.perform(
        put("/carts/" + cartId + "/items/" + sku)
            .contentType(MediaType.APPLICATION_JSON)
            .content("{\"quantity\":1}"));
    String key = Ids.newId();
    var pool = java.util.concurrent.Executors.newFixedThreadPool(8);
    var futures = new java.util.ArrayList<java.util.concurrent.Future<Integer>>();
    var go = new java.util.concurrent.CountDownLatch(1);
    for (int i = 0; i < 8; i++) {
      futures.add(
          pool.submit(
              () -> {
                go.await();
                return checkout(key, checkoutBody(cartId, 12999)).getResponse().getStatus();
              }));
    }
    go.countDown();
    List<Integer> codes = new java.util.ArrayList<>();
    for (var f : futures) {
      codes.add(f.get());
    }
    pool.shutdown();
    // Exactly one execution; the others either raced into the lock (409) or replayed the stored
    // 202.
    assertThat(codes).allMatch(c -> c == 202 || c == 409);
    assertThat(
            driver.published().stream()
                .filter(
                    p ->
                        p.record() instanceof CheckoutSubmitted
                            && ((CheckoutSubmitted) p.record()).getCartId().equals(cartId)))
        .hasSize(1);
    assertThat(Map.of()).isEmpty();
  }
}
