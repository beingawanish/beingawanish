package com.edacommerce.returns.adapters.in.http;

import com.edacommerce.edacommon.http.ApiProblem;
import com.edacommerce.returns.application.NotWaitingForDecisionException;
import com.edacommerce.returns.application.ReturnsService;
import com.edacommerce.returns.domain.ReturnSagaTrigger;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code POST /ops/returns/{id}/decision} (returns.yaml): the human decision point of the returns
 * saga, for high-value returns (MANUAL_REVIEW) and refunds that kept failing (REFUND_REVIEW).
 */
@RestController
public class ReturnsOpsController {

  /** The decision body. */
  public record DecisionRequest(@NotBlank String decision, @Size(max = 1000) String note) {}

  private final ReturnsService returns;

  public ReturnsOpsController(ReturnsService returns) {
    this.returns = returns;
  }

  @PostMapping("/ops/returns/{returnId}/decision")
  public ResponseEntity<ReturnJson> decide(
      @PathVariable("returnId") String returnId, @Valid @RequestBody DecisionRequest body) {
    ReturnSagaTrigger.Decision.Kind kind = kind(body.decision());
    try {
      return ResponseEntity.status(HttpStatus.ACCEPTED)
          .body(
              ReturnJson.of(
                  ReturnsController.translate(() -> returns.decide(returnId, kind, body.note()))));
    } catch (NotWaitingForDecisionException e) {
      throw ApiProblem.conflict("return-not-waiting", "Not waiting for a decision", e.getMessage());
    }
  }

  static ReturnSagaTrigger.Decision.Kind kind(String raw) {
    for (ReturnSagaTrigger.Decision.Kind k : ReturnSagaTrigger.Decision.Kind.values()) {
      if (k.name().equals(raw)) {
        return k;
      }
    }
    throw ApiProblem.badRequest(
        "validation-failed",
        "unknown decision",
        List.of(
            new ApiProblem.FieldError(
                "decision", "one of " + List.of(ReturnSagaTrigger.Decision.Kind.values()))));
  }
}
