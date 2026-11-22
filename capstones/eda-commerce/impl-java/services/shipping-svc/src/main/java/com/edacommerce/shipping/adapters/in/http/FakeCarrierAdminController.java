package com.edacommerce.shipping.adapters.in.http;

import com.edacommerce.edacommon.http.ApiProblem;
import com.edacommerce.shipping.adapters.out.carrier.fake.FakeCarrier;
import com.edacommerce.shipping.adapters.out.carrier.fake.FakeCarrierConfig;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/** The fake carrier's knobs (admin.yaml): the chaos drills and the returns tests use them. */
@RestController
public class FakeCarrierAdminController {
  static final Set<String> STATUSES =
      Set.of("PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED", "EXCEPTION");

  /** admin.yaml advanceShipment request body. */
  record Advance(String toStatus) {}

  private final FakeCarrier carrier;

  public FakeCarrierAdminController(FakeCarrier carrier) {
    this.carrier = carrier;
  }

  /** Not in admin.yaml; a convenience for operators, like GET /admin/fakes/psp. */
  @GetMapping("/admin/fakes/carrier")
  public FakeCarrierConfig get() {
    return carrier.config();
  }

  /** Merges the given fields into the current behaviour; omitted fields keep their value. */
  @PutMapping("/admin/fakes/carrier")
  public ResponseEntity<Void> put(@RequestBody FakeCarrierConfig patch) {
    carrier.update(patch);
    return ResponseEntity.ok().build();
  }

  @PostMapping("/admin/fakes/carrier/shipments/{trackingNumber}/advance")
  public ResponseEntity<Void> advance(
      @PathVariable("trackingNumber") String trackingNumber,
      @RequestBody(required = false) Advance body) {
    String to = body == null ? null : body.toStatus();
    if (to != null && !STATUSES.contains(to)) {
      throw ApiProblem.badRequest(
          "validation-failed",
          "unknown toStatus",
          java.util.List.of(new ApiProblem.FieldError("toStatus", "one of " + STATUSES)));
    }
    if (!carrier.advance(trackingNumber, to)) {
      throw ApiProblem.notFound("tracking number " + trackingNumber);
    }
    return ResponseEntity.status(HttpStatus.ACCEPTED).build();
  }
}
