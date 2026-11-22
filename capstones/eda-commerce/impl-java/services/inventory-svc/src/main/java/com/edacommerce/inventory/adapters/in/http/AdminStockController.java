package com.edacommerce.inventory.adapters.in.http;

import com.edacommerce.edacommon.http.ApiProblem;
import com.edacommerce.inventory.application.InventoryUseCases;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/** {@code PUT /admin/stock/{sku}} (admin.yaml setStock), used by infra/scripts/seed.sh. */
@RestController
public class AdminStockController {

  /** Request body. */
  public record SetStock(@NotNull @Min(0) Integer onHand) {}

  private final InventoryUseCases useCases;

  public AdminStockController(InventoryUseCases useCases) {
    this.useCases = useCases;
  }

  @PutMapping("/admin/stock/{sku}")
  public ResponseEntity<Void> setStock(@PathVariable("sku") String sku, @Valid @RequestBody SetStock body) {
    try {
      useCases.setStock(sku, body.onHand());
    } catch (DataIntegrityViolationException e) {
      throw ApiProblem.unprocessable(
          "stock-below-reserved", "On-hand below reserved", "on-hand stock cannot be set below the reserved quantity");
    }
    return ResponseEntity.ok().build();
  }
}
