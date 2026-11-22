package com.edacommerce.shipping;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/** shipping-svc: carrier bookings, labels, tracking normalisation. */
@SpringBootApplication
public class ShippingServiceApplication {
  public static void main(String[] args) {
    SpringApplication.run(ShippingServiceApplication.class, args);
  }
}
