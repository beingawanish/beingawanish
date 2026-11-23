package com.edacommerce.payment;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/** payment-svc: authorise, capture, void, refund; fake PSP; webhook endpoint; reconciliation. */
@SpringBootApplication
public class PaymentServiceApplication {
  public static void main(String[] args) {
    SpringApplication.run(PaymentServiceApplication.class, args);
  }
}
