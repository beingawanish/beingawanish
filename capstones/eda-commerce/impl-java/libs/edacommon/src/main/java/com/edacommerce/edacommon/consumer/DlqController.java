package com.edacommerce.edacommon.consumer;

import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code GET /ops/dlq} and {@code POST /ops/dlq/replay} (admin.yaml), on every consuming service.
 */
@RestController
public class DlqController {
  private final DlqService dlq;

  public DlqController(DlqService dlq) {
    this.dlq = dlq;
  }

  @GetMapping("/ops/dlq")
  public List<DlqEntry> list(@RequestParam(name = "limit", defaultValue = "50") int limit) {
    return dlq.peek(limit);
  }

  /** The Idempotency-Key header is enforced by the idempotency filter (ADR-0012). */
  @PostMapping("/ops/dlq/replay")
  public ResponseEntity<Map<String, Integer>> replay(
      @RequestBody DlqService.ReplayRequest request) {
    return ResponseEntity.status(HttpStatus.ACCEPTED).body(Map.of("replayed", dlq.replay(request)));
  }
}
