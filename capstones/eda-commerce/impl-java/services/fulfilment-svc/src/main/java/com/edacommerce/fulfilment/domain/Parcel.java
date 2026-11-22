package com.edacommerce.fulfilment.domain;

/** A packed parcel as the warehouse reports it. */
public record Parcel(String parcelId, int weightGrams, int lengthMm, int widthMm, int heightMm) {}
