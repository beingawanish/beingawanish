package com.edacommerce.returns.adapters.in.http;

import com.edacommerce.common.ClaimCheck;
import com.edacommerce.edacommon.claimcheck.ClaimCheckStore;
import com.edacommerce.edacommon.http.ApiProblem;
import com.edacommerce.edacommon.http.Caller;
import com.edacommerce.returns.application.ReturnNotFoundException;
import com.edacommerce.returns.application.ReturnView;
import com.edacommerce.returns.application.ReturnsService;
import com.edacommerce.returns.domain.Eligibility;
import com.edacommerce.returns.domain.IneligibleReturnException;
import com.edacommerce.returns.domain.LabelRef;
import com.edacommerce.returns.domain.ReturnReason;
import com.edacommerce.returns.domain.ReturnsException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.net.URI;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.function.Supplier;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/**
 * Returns API (contracts/openapi/returns.yaml). Idempotency-Key is handled by the edacommon filter;
 * eligibility is answered synchronously from returns-svc's own projection.
 */
@RestController
public class ReturnsController {
  static final Duration LABEL_URL_TTL = Duration.ofMinutes(5);

  /** returns.yaml ReturnRequest. */
  public record ReturnRequest(
      @NotBlank String orderId,
      @NotEmpty List<@Valid Line> lines,
      @NotBlank String reason,
      @Size(max = 1000) String comment) {
    /** A requested line. */
    public record Line(@NotBlank String lineId, @NotNull @Min(1) Integer quantity) {}
  }

  /** GET /orders/{orderId}/returns. */
  public record OrderReturnsJson(
      List<ReturnJson> returns, List<ReturnableJson> returnable, Instant windowEndsAt) {}

  /** One returnable line. */
  public record ReturnableJson(String lineId, String sku, int quantity) {}

  private final ReturnsService returns;
  private final ClaimCheckStore documents;
  private final Caller caller;

  public ReturnsController(ReturnsService returns, ClaimCheckStore documents, Caller caller) {
    this.returns = returns;
    this.documents = documents;
    this.caller = caller;
  }

  @PostMapping("/returns")
  public ResponseEntity<ReturnJson> request(
      @Valid @RequestBody ReturnRequest body, HttpServletRequest http) {
    ReturnReason reason = reason(body.reason());
    ReturnView v =
        translate(
            () ->
                returns.request(
                    caller.id(http),
                    body.orderId(),
                    body.lines().stream()
                        .map(l -> new Eligibility.Requested(l.lineId(), l.quantity()))
                        .toList(),
                    reason,
                    body.comment()));
    return ResponseEntity.status(HttpStatus.ACCEPTED)
        .location(URI.create("/returns/" + v.returnId()))
        .body(ReturnJson.of(v));
  }

  @GetMapping("/returns/{returnId}")
  public ReturnJson get(@PathVariable("returnId") String returnId, HttpServletRequest http) {
    return ReturnJson.of(translate(() -> returns.get(returnId, caller.id(http))));
  }

  /** 302 to a pre-signed URL valid for 5 minutes (ADR-0009); 404 while there is no label. */
  @GetMapping("/returns/{returnId}/label")
  public ResponseEntity<Void> label(
      @PathVariable("returnId") String returnId, HttpServletRequest http) {
    ReturnView v = translate(() -> returns.get(returnId, caller.id(http)));
    LabelRef l = v.label();
    if (l == null) {
      throw ApiProblem.of(
          HttpStatus.NOT_FOUND,
          "label-not-ready",
          "No label yet",
          "shipping-svc has not booked the return label yet");
    }
    ClaimCheck claim =
        ClaimCheck.newBuilder()
            .setBucket(l.bucket())
            .setObjectKey(l.objectKey())
            .setContentType(l.contentType())
            .setSizeBytes(l.sizeBytes())
            .setSha256(l.sha256())
            .setExpiresAt(l.expiresAt())
            .build();
    URI url = URI.create(documents.presign(claim, LABEL_URL_TTL).toString());
    return ResponseEntity.status(HttpStatus.FOUND).location(url).build();
  }

  @GetMapping("/orders/{orderId}/returns")
  public OrderReturnsJson forOrder(
      @PathVariable("orderId") String orderId, HttpServletRequest http) {
    ReturnsService.OrderReturns r = translate(() -> returns.forOrder(orderId, caller.id(http)));
    return new OrderReturnsJson(
        r.returns().stream().map(ReturnJson::of).toList(),
        r.returnable().stream()
            .map(x -> new ReturnableJson(x.lineId(), x.sku(), x.quantity()))
            .toList(),
        r.windowEndsAt());
  }

  static ReturnReason reason(String raw) {
    for (ReturnReason r : ReturnReason.values()) {
      if (r.name().equals(raw)) {
        return r;
      }
    }
    throw ApiProblem.badRequest(
        "validation-failed",
        "unknown return reason",
        List.of(new ApiProblem.FieldError("reason", "one of " + List.of(ReturnReason.values()))));
  }

  /** Domain and application errors -> problem details (guide §6.3). */
  static <T> T translate(Supplier<T> call) {
    try {
      return call.get();
    } catch (ReturnNotFoundException e) {
      throw ApiProblem.of(HttpStatus.NOT_FOUND, "not-found", "Not found", e.getMessage());
    } catch (IneligibleReturnException e) {
      String slug =
          switch (e.reason()) {
            case NOT_DELIVERED -> "return-not-delivered";
            case WINDOW_CLOSED -> "return-window-closed";
            case QUANTITY_EXCEEDED -> "return-quantity-exceeded";
            case UNKNOWN_LINE -> "return-unknown-line";
          };
      throw ApiProblem.unprocessable(slug, "Not eligible for return", e.getMessage());
    } catch (ReturnsException e) {
      throw ApiProblem.badRequest("validation-failed", e.getMessage(), List.of());
    }
  }
}
