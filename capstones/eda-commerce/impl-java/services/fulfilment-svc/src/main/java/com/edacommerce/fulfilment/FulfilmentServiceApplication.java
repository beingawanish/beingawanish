package com.edacommerce.fulfilment;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/** fulfilment-svc: pick, pack, dispatch; returns intake and inspection. */
@SpringBootApplication
public class FulfilmentServiceApplication {
  public static void main(String[] args) {
    SpringApplication.run(FulfilmentServiceApplication.class, args);
  }
}
