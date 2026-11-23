package com.edacommerce.catalog.adapters.in.http;

import com.edacommerce.catalog.application.CatalogUseCases;
import com.edacommerce.catalog.domain.Availability;
import com.edacommerce.catalog.domain.CatalogException;
import com.edacommerce.catalog.domain.Product;
import com.edacommerce.catalog.domain.ProductStatus;
import com.edacommerce.edacommon.http.ApiProblem;
import com.edacommerce.kernel.Money;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.PositiveOrZero;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Catalog API (contracts/openapi/catalog.yaml). */
@RestController
public class ProductController {

  /** common.yaml Money. */
  public record MoneyJson(
      @NotNull @PositiveOrZero Long amountMinor,
      @NotBlank @Pattern(regexp = "^[A-Z]{3}$") String currency) {
    Money toMoney() {
      return Money.of(amountMinor, currency);
    }

    static MoneyJson of(Money m) {
      return m == null ? null : new MoneyJson(m.amountMinor(), m.currency());
    }
  }

  /** catalog.yaml ProductWrite. */
  public record ProductWrite(
      @NotBlank String name,
      String description,
      String brand,
      List<String> categoryPath,
      Map<String, String> attributes,
      @NotNull ProductStatus status,
      Integer weightGrams,
      List<String> imageUrls,
      @NotNull @Valid MoneyJson listPrice,
      @Valid MoneyJson salePrice) {}

  /**
   * catalog.yaml ProductView. Absent optional fields are omitted (guide §5 rule 10: null means
   * absent).
   */
  @com.fasterxml.jackson.annotation.JsonInclude(
      com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
  public record ProductView(
      String sku,
      String name,
      String description,
      String brand,
      List<String> categoryPath,
      Map<String, String> attributes,
      String status,
      Integer weightGrams,
      List<String> imageUrls,
      MoneyJson listPrice,
      MoneyJson salePrice,
      String availability,
      long version) {}

  private final CatalogUseCases catalog;

  public ProductController(CatalogUseCases catalog) {
    this.catalog = catalog;
  }

  @GetMapping("/products")
  public Map<String, Object> list(
      @RequestParam(name = "category", required = false) String category,
      @RequestParam(name = "q", required = false) String q,
      @RequestParam(name = "cursor", required = false) String cursor,
      @RequestParam(name = "limit", defaultValue = "24") int limit) {
    if (limit < 1 || limit > 100) {
      throw ApiProblem.badRequest(
          "validation",
          "limit must be 1..100",
          List.of(new ApiProblem.FieldError("limit", "1..100")));
    }
    String after = null;
    if (cursor != null && !cursor.isBlank()) {
      try {
        after = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8);
      } catch (IllegalArgumentException e) {
        throw ApiProblem.badRequest(
            "validation",
            "invalid cursor",
            List.of(new ApiProblem.FieldError("cursor", "invalid")));
      }
    }
    List<Product> page = catalog.browse(category, q, after, limit + 1);
    String next = null;
    if (page.size() > limit) {
      page = page.subList(0, limit);
      next =
          Base64.getUrlEncoder()
              .withoutPadding()
              .encodeToString(page.get(limit - 1).sku().getBytes(StandardCharsets.UTF_8));
    }
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("items", page.stream().map(this::view).toList());
    body.put("nextCursor", next);
    return body;
  }

  @GetMapping("/products/{sku}")
  public ResponseEntity<ProductView> get(@PathVariable("sku") String sku) {
    Product p = catalog.find(sku).orElseThrow(() -> ApiProblem.notFound("product " + sku));
    return ResponseEntity.ok().eTag("\"" + p.version() + "\"").body(view(p));
  }

  @PutMapping("/admin/products/{sku}")
  public ProductView upsert(@PathVariable("sku") String sku, @Valid @RequestBody ProductWrite w) {
    try {
      Product p =
          catalog.upsert(
              new Product(
                  sku,
                  w.name(),
                  w.description(),
                  w.brand(),
                  w.categoryPath(),
                  w.attributes(),
                  w.status(),
                  w.weightGrams(),
                  w.imageUrls(),
                  w.listPrice().toMoney(),
                  w.salePrice() == null ? null : w.salePrice().toMoney(),
                  0,
                  0));
      return view(p);
    } catch (CatalogException e) {
      throw ApiProblem.badRequest("invalid-product", e.getMessage(), List.of());
    }
  }

  private ProductView view(Product p) {
    return new ProductView(
        p.sku(),
        p.name(),
        p.description(),
        p.brand(),
        p.categoryPath(),
        p.attributes(),
        p.status().name(),
        p.weightGrams(),
        p.imageUrls(),
        MoneyJson.of(p.listPrice()),
        MoneyJson.of(p.salePrice()),
        Availability.of(catalog.available(p.sku())).name(),
        p.version());
  }
}
