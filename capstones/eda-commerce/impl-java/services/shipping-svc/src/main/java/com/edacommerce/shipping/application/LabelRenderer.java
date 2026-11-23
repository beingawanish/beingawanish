package com.edacommerce.shipping.application;

import com.edacommerce.shipping.domain.Shipment;

/** Port: renders the shipping label PDF for a booked shipment. */
public interface LabelRenderer {
  byte[] render(Shipment shipment, String carrier, String trackingNumber);
}
