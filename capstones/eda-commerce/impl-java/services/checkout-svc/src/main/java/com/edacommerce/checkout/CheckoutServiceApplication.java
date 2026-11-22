package com.edacommerce.checkout;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/** checkout-svc: carts and checkout submission. */
@SpringBootApplication
public class CheckoutServiceApplication {
  public static void main(String[] args) {
    SpringApplication.run(CheckoutServiceApplication.class, args);
  }
}
