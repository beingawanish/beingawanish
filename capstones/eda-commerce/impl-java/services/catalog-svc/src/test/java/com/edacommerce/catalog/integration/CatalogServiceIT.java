package com.edacommerce.catalog.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.edacommerce.catalog.PriceChanged;
import com.edacommerce.catalog.ProductUpserted;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.ids.Ids;
import com.edacommerce.edacommon.testing.EdaServiceTest;
import com.edacommerce.edacommon.testing.MessageDriver;
import com.edacommerce.edacommon.testing.OpenApiContract;
import com.edacommerce.edacommon.testing.SharedTables;
import com.edacommerce.inventory.StockLevelChanged;
import java.time.Instant;
import javax.sql.DataSource;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

@EdaServiceTest
class CatalogServiceIT {
  @Autowired ApplicationContext ctx;
  @Autowired MockMvc mvc;
  @Autowired DataSource dataSource;

  static String body(long price) {
    return "{\"name\":\"Trail Running Shoe\",\"brand\":\"Northpeak\",\"categoryPath\":[\"Sport\",\"Footwear\"],"
        + "\"attributes\":{\"colour\":\"blue\"},\"status\":\"ACTIVE\",\"weightGrams\":620,"
        + "\"listPrice\":{\"amountMinor\":"
        + price
        + ",\"currency\":\"EUR\"}}";
  }

  @Test
  void sharedTablesMatchTheContract() {
    SharedTables.assertMatchesContract(dataSource);
  }

  @Test
  void upsertPublishesSnapshotsAndBrowseServesTheProduct() throws Exception {
    MessageDriver driver = new MessageDriver(ctx);
    String sku = "SKU-" + Ids.newId().substring(28);
    mvc.perform(
            put("/admin/products/" + sku)
                .contentType(MediaType.APPLICATION_JSON)
                .content(body(12999)))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.availability").value("UNKNOWN"))
        .andExpect(OpenApiContract.validResponse("catalog.yaml"));
    mvc.perform(
            put("/admin/products/" + sku)
                .contentType(MediaType.APPLICATION_JSON)
                .content(body(12999)))
        .andExpect(status().isOk());
    mvc.perform(
            put("/admin/products/" + sku)
                .contentType(MediaType.APPLICATION_JSON)
                .content(body(9999)))
        .andExpect(status().isOk());
    assertThat(driver.published(ProductUpserted.class, sku))
        .extracting(p -> p.getEnvelope().getAggregateVersion())
        .containsExactly(1L, 2L, 3L);
    assertThat(driver.published(PriceChanged.class, sku))
        .extracting(p -> p.getListPrice().getAmountMinor())
        .containsExactly(12999L, 9999L);

    driver.deliver(
        "inventory.stock-level.v1",
        sku,
        StockLevelChanged.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setSku(sku)
            .setOnHand(3)
            .setReserved(0)
            .setAvailable(3)
            .setAsOf(Instant.now())
            .build());
    mvc.perform(get("/products/" + sku))
        .andExpect(status().isOk())
        .andExpect(header().string("ETag", "\"3\""))
        .andExpect(jsonPath("$.availability").value("LOW_STOCK"))
        .andExpect(OpenApiContract.validResponse("catalog.yaml"));
    mvc.perform(
            get("/products")
                .param("category", "Footwear")
                .param("q", "trail")
                .param("limit", "100"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.items[?(@.sku=='" + sku + "')]").exists())
        .andExpect(OpenApiContract.validResponse("catalog.yaml"));
    mvc.perform(get("/products/NOPE")).andExpect(status().isNotFound());
    mvc.perform(
            put("/admin/products/" + sku)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"name\":\"x\"}"))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.errors").isArray());
  }
}
