package com.edacommerce.fulfilment.domain;

import java.util.ArrayList;
import java.util.List;
import java.util.function.IntFunction;

/** Splits picked units into parcels a carrier accepts (at most 20 kg each). */
public final class ParcelPlan {
  private ParcelPlan() {}

  public static final int GRAMS_PER_UNIT = 450;
  public static final int MAX_GRAMS = 20_000;

  public static List<Parcel> plan(List<OrderLine> lines, IntFunction<String> parcelIdOf) {
    int units = lines.stream().mapToInt(OrderLine::quantity).sum();
    int total = Math.max(units * GRAMS_PER_UNIT, 1);
    List<Parcel> parcels = new ArrayList<>();
    for (int i = 0; total > 0; i++) {
      int w = Math.min(total, MAX_GRAMS);
      parcels.add(new Parcel(parcelIdOf.apply(i), w, 400, 300, w < 5000 ? 150 : 300));
      total -= w;
    }
    return List.copyOf(parcels);
  }
}
