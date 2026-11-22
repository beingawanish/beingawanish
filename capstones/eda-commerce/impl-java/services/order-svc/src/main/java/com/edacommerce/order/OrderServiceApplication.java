package com.edacommerce.order;

import java.util.Arrays;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * order-svc. {@code java -jar order-svc.jar} runs the saga and the Orders API; {@code ... projector}
 * runs the order-history projector from the same image (compose.apps.example.yml).
 */
@SpringBootApplication
public class OrderServiceApplication {
  public static void main(String[] args) {
    SpringApplication app = new SpringApplication(OrderServiceApplication.class);
    if (Arrays.asList(args).contains("projector")) {
      app.setAdditionalProfiles("projector");
    }
    app.run(args);
  }
}
