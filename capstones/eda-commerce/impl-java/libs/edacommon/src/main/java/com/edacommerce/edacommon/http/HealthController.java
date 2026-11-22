package com.edacommerce.edacommon.http;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code /health/live}: the process is up. {@code /health/ready}: DB reachable, schema cache warm,
 * consumer subscribed (guide §6.5).
 */
@RestController
public class HealthController {
  private final List<ReadinessCheck> checks;

  public HealthController(List<ReadinessCheck> checks) {
    this.checks = checks;
  }

  @GetMapping("/health/live")
  public Map<String, String> live() {
    return Map.of("status", "UP");
  }

  @GetMapping("/health/ready")
  public ResponseEntity<Map<String, Object>> ready() {
    Map<String, Object> details = new LinkedHashMap<>();
    boolean all = true;
    for (ReadinessCheck check : checks) {
      boolean ok;
      try {
        ok = check.ready();
      } catch (RuntimeException e) {
        ok = false;
      }
      details.put(check.name(), ok ? "UP" : "DOWN");
      all &= ok;
    }
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("status", all ? "UP" : "DOWN");
    body.put("checks", details);
    return ResponseEntity.status(all ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE).body(body);
  }
}
