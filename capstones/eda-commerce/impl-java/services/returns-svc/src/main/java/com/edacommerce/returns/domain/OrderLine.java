package com.edacommerce.returns.domain;

/** A delivered order line as the eligibility view knows it (prices in minor units). */
public record OrderLine(
    String lineId, String sku, String productName, int quantity, long unitPriceMinor) {}
