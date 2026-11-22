package com.edacommerce.checkout.adapters.in.http;

import com.edacommerce.checkout.application.CheckoutUseCases;
import com.edacommerce.checkout.domain.Cart;
import com.edacommerce.checkout.domain.CheckoutException;
import com.edacommerce.checkout.domain.Pricing;
import com.edacommerce.common.Address;
import com.edacommerce.edacommon.http.ApiProblem;
import com.edacommerce.edacommon.http.Caller;
import com.edacommerce.kernel.Money;
import com.fasterxml.jackson.annotation.JsonInclude;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.net.URI;
import java.time.Instant;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

/**
 * Checkout API (contracts/openapi/checkout.yaml). Idempotency-Key is handled by the edacommon
 * filter.
 */
@RestController
public class CheckoutController {
  private final CheckoutUseCases useCases;
  private final Caller caller;
  private final com.edacommerce.edacommon.http.ProblemHandler problems =
      new com.edacommerce.edacommon.http.ProblemHandler();

  public CheckoutController(CheckoutUseCases useCases, Caller caller) {
    this.useCases = useCases;
    this.caller = caller;
  }

  /** common.yaml Money. */
  public record MoneyJson(
      @NotNull Long amountMinor, @NotBlank @Pattern(regexp = "^[A-Z]{3}$") String currency) {
    static MoneyJson of(Money m) {
      return new MoneyJson(m.amountMinor(), m.currency());
    }
  }

  /** common.yaml Address. */
  public record AddressJson(
      @NotBlank @Size(max = 200) String recipientName,
      @NotBlank @Size(max = 200) String line1,
      @Size(max = 200) String line2,
      @NotBlank @Size(max = 100) String city,
      @Size(max = 100) String region,
      @NotBlank @Size(max = 20) String postalCode,
      @NotBlank @Pattern(regexp = "^[A-Z]{2}$") String countryCode,
      @Size(max = 30) String phone) {}

  /** checkout.yaml CheckoutRequest. */
  public record CheckoutRequest(
      @NotBlank String cartId,
      @NotNull @Valid AddressJson shippingAddress,
      @NotBlank @Email String contactEmail,
      @NotBlank @Pattern(regexp = "STANDARD|EXPRESS") String shippingMethod,
      @NotBlank String paymentMethodToken,
      @NotNull @Valid MoneyJson expectedTotal) {}

  /** POST /carts body. */
  public record CreateCart(@Pattern(regexp = "^[A-Z]{3}$") String currency) {}

  /** PUT item body. */
  public record SetItem(@NotNull @Min(1) @Max(99) Integer quantity) {}

  /** checkout.yaml CartLine. */
  public record CartLineJson(
      String sku,
      String productName,
      int quantity,
      MoneyJson unitPrice,
      MoneyJson lineTotal,
      String availability) {}

  /** checkout.yaml Cart. */
  public record CartJson(
      String cartId,
      String status,
      List<CartLineJson> lines,
      MoneyJson subtotal,
      Instant pricedAt) {}

  /** checkout.yaml CheckoutAccepted. */
  @JsonInclude(JsonInclude.Include.NON_NULL)
  public record AcceptedJson(
      String checkoutId, String orderId, String status, MoneyJson total, String statusUrl) {}

  @PostMapping("/carts")
  public ResponseEntity<CartJson> create(
      @Valid @RequestBody(required = false) CreateCart body, HttpServletRequest request) {
    String currency = body == null || body.currency() == null ? "EUR" : body.currency();
    Cart cart = useCases.create(caller.id(request), currency);
    return ResponseEntity.created(URI.create("/carts/" + cart.cartId()))
        .eTag(etag(cart))
        .body(json(cart));
  }

  @GetMapping("/carts/{cartId}")
  public ResponseEntity<CartJson> get(
      @PathVariable("cartId") String cartId, HttpServletRequest request) {
    Cart cart =
        useCases
            .find(cartId, caller.id(request))
            .orElseThrow(() -> ApiProblem.notFound("cart " + cartId));
    return ResponseEntity.ok().eTag(etag(cart)).body(json(cart));
  }

  @PutMapping("/carts/{cartId}/items/{sku}")
  public ResponseEntity<CartJson> setItem(
      @PathVariable("cartId") String cartId,
      @PathVariable("sku") String sku,
      @RequestHeader(name = "If-Match", required = false) String ifMatch,
      @Valid @RequestBody SetItem body,
      HttpServletRequest request) {
    Cart cart =
        useCases.setItem(cartId, caller.id(request), sku, body.quantity(), parseEtag(ifMatch));
    return ResponseEntity.ok().eTag(etag(cart)).body(json(cart));
  }

  @DeleteMapping("/carts/{cartId}/items/{sku}")
  public CartJson removeItem(
      @PathVariable("cartId") String cartId,
      @PathVariable("sku") String sku,
      HttpServletRequest request) {
    return json(useCases.removeItem(cartId, caller.id(request), sku));
  }

  @PostMapping("/checkouts")
  public ResponseEntity<AcceptedJson> submit(
      @Valid @RequestBody CheckoutRequest r, HttpServletRequest request) {
    AddressJson a = r.shippingAddress();
    CheckoutUseCases.Accepted accepted =
        useCases.submit(
            caller.id(request),
            new CheckoutUseCases.SubmitCommand(
                r.cartId(),
                new Address(
                    a.recipientName(),
                    a.line1(),
                    a.line2(),
                    a.city(),
                    a.region(),
                    a.postalCode(),
                    a.countryCode(),
                    a.phone()),
                r.contactEmail(),
                r.shippingMethod(),
                r.paymentMethodToken(),
                Money.of(r.expectedTotal().amountMinor(), r.expectedTotal().currency())));
    String statusUrl = "/orders/" + accepted.orderId();
    return ResponseEntity.status(HttpStatus.ACCEPTED)
        .location(URI.create(statusUrl))
        .header("Retry-After", "1")
        .body(
            new AcceptedJson(
                accepted.checkoutId(),
                accepted.orderId(),
                "PENDING",
                MoneyJson.of(accepted.total()),
                statusUrl));
  }

  /** Domain rule violations: 404 for unknown carts, 412 for a stale If-Match, 422 otherwise. */
  @ExceptionHandler(CheckoutException.class)
  public ResponseEntity<org.springframework.http.ProblemDetail> rule(
      CheckoutException e, HttpServletRequest request) {
    ApiProblem p =
        switch (e.code()) {
          case "not-found" -> ApiProblem.notFound(e.getMessage());
          case "precondition-failed" -> ApiProblem.preconditionFailed(e.getMessage());
          default ->
              ApiProblem.unprocessable(e.code(), "Request cannot be processed", e.getMessage());
        };
    return problems.api(p, request);
  }

  CartJson json(Cart cart) {
    Pricing.Priced p = useCases.price(cart);
    return new CartJson(
        cart.cartId(),
        cart.status().name(),
        p.lines().stream()
            .map(
                l ->
                    new CartLineJson(
                        l.sku(),
                        l.productName(),
                        l.quantity(),
                        MoneyJson.of(l.unitPrice()),
                        MoneyJson.of(l.lineTotal()),
                        l.availability()))
            .toList(),
        MoneyJson.of(p.subtotal()),
        p.pricedAt());
  }

  static String etag(Cart cart) {
    return "\"" + cart.version() + "\"";
  }

  static Long parseEtag(String ifMatch) {
    if (ifMatch == null || ifMatch.isBlank() || ifMatch.equals("*")) {
      return null;
    }
    try {
      return Long.valueOf(ifMatch.replace("W/", "").replace("\"", "").trim());
    } catch (NumberFormatException e) {
      return -1L;
    }
  }
}
