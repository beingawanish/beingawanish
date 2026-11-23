package com.edacommerce.inventory.domain;

/** Why a reservation was rejected for one SKU. */
public record Shortage(String sku, int requested, int available) {}
