package com.edacommerce.catalog.domain;

import com.edacommerce.kernel.Money;
import java.util.List;
import java.util.Map;

/** A product with its current default-list price. catalog-svc is its owner (architecture §3). */
public record Product(
    String sku,
    String name,
    String description,
    String brand,
    List<String> categoryPath,
    Map<String, String> attributes,
    ProductStatus status,
    Integer weightGrams,
    List<String> imageUrls,
    Money listPrice,
    Money salePrice,
    long version,
    long priceVersion) {

  public Product {
    if (sku == null || sku.isBlank() || sku.length() > 64) {
      throw new CatalogException("sku must be 1-64 characters");
    }
    if (name == null || name.isBlank()) {
      throw new CatalogException("name is required");
    }
    if (listPrice == null || listPrice.isNegative()) {
      throw new CatalogException("listPrice must be a non-negative amount");
    }
    if (salePrice != null
        && (!salePrice.currency().equals(listPrice.currency()) || salePrice.isNegative())) {
      throw new CatalogException("salePrice must be non-negative and in the list price currency");
    }
    categoryPath = categoryPath == null ? List.of() : List.copyOf(categoryPath);
    attributes = attributes == null ? Map.of() : Map.copyOf(attributes);
    imageUrls = imageUrls == null ? List.of() : List.copyOf(imageUrls);
  }

  /**
   * The result of an upsert: the stored product and whether the price snapshot must be republished.
   */
  public record Upsert(Product product, boolean priceChanged) {}

  /**
   * Create or replace. Every upsert bumps the product version; a price change also bumps the price
   * version.
   */
  public static Upsert upsert(Product previous, Product incoming) {
    if (previous == null) {
      return new Upsert(incoming.withVersions(1, 1), true);
    }
    boolean priceChanged =
        !previous.listPrice.equals(incoming.listPrice)
            || !java.util.Objects.equals(previous.salePrice, incoming.salePrice);
    return new Upsert(
        incoming.withVersions(
            previous.version + 1, priceChanged ? previous.priceVersion + 1 : previous.priceVersion),
        priceChanged);
  }

  Product withVersions(long v, long pv) {
    return new Product(
        sku,
        name,
        description,
        brand,
        categoryPath,
        attributes,
        status,
        weightGrams,
        imageUrls,
        listPrice,
        salePrice,
        v,
        pv);
  }
}
