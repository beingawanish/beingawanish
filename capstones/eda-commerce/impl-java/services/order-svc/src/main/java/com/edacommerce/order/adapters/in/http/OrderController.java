package com.edacommerce.order.adapters.in.http;

import com.edacommerce.edacommon.http.ApiProblem;
import com.edacommerce.edacommon.http.Caller;
import com.edacommerce.kernel.Money;
import com.edacommerce.order.application.OrderQueries;
import com.edacommerce.order.application.OrderView;
import com.edacommerce.order.domain.OrderStatus;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import java.time.Instant;
import java.util.Arrays;
import java.util.EnumSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Orders API (contracts/openapi/orders.yaml). */
@RestController
@Profile("!projector")
public class OrderController {
  private final OrderQueries queries;
  private final Caller caller;

  public OrderController(OrderQueries queries, Caller caller) {
    this.queries = queries;
    this.caller = caller;
  }

  /** orders.yaml Order: the summary fields plus details. */
  public record OrderJson(String orderId, String status, MoneyJson total, int itemCount, Instant placedAt, long version,
      List<LineJson> lines, String cancellationReason, ShipmentJson shipment, boolean invoiceAvailable, MoneyJson refundedTotal,
      List<TimelineJson> timeline, String source) {}

  /** orders.yaml OrderSummary. */
  public record SummaryJson(String orderId, String status, MoneyJson total, int itemCount, Instant placedAt, long version) {}

  /** common.yaml Money. */
  public record MoneyJson(long amountMinor, String currency) {
    static MoneyJson of(Money m) {
      return new MoneyJson(m.amountMinor(), m.currency());
    }
  }

  /** An order line. */
  public record LineJson(String lineId, String sku, String productName, int quantity, MoneyJson unitPrice, MoneyJson lineTotal,
      int returnedQuantity) {}

  /** Carrier and tracking. */
  public record ShipmentJson(String carrier, String trackingNumber, String status) {}

  /** orders.yaml TimelineEntry. */
  public record TimelineJson(Instant at, String kind, String description, String eventId) {}

  @GetMapping("/orders/{orderId}")
  public ResponseEntity<OrderJson> get(@PathVariable("orderId") String orderId,
      @RequestHeader(name = "If-None-Match", required = false) String ifNoneMatch, HttpServletRequest request) {
    OrderView v = queries.get(orderId, caller.id(request)).orElseThrow(() -> ApiProblem.notFound("order " + orderId));
    String etag = "\"" + v.version() + "\"";
    ResponseEntity.BodyBuilder ok = ResponseEntity.ok().eTag(etag);
    if (!v.terminal()) {
      ok.header("Retry-After", "2");
    }
    if (etag.equals(ifNoneMatch)) {
      return ResponseEntity.status(HttpStatus.NOT_MODIFIED).eTag(etag).build();
    }
    return ok.body(json(v));
  }

  @GetMapping("/orders/{orderId}/invoice")
  public ResponseEntity<Void> invoice(@PathVariable("orderId") String orderId, HttpServletRequest request) {
    URI url = queries.invoiceUrl(orderId, caller.id(request)).map(u -> URI.create(u.toString()))
        .orElseThrow(() -> ApiProblem.notFound("invoice for order " + orderId));
    return ResponseEntity.status(HttpStatus.FOUND).location(url).build();
  }

  @GetMapping("/customers/me/orders")
  public Map<String, Object> mine(@RequestParam(name = "cursor", required = false) String cursor,
      @RequestParam(name = "limit", defaultValue = "20") int limit,
      @RequestParam(name = "status", required = false) String status, HttpServletRequest request) {
    if (limit < 1 || limit > 100) {
      throw ApiProblem.badRequest("validation", "limit must be between 1 and 100", List.of(new ApiProblem.FieldError("limit", "1..100")));
    }
    Set<OrderStatus> statuses = EnumSet.noneOf(OrderStatus.class);
    if (status != null && !status.isBlank()) {
      try {
        Arrays.stream(status.split(",")).map(String::trim).map(OrderStatus::valueOf).forEach(statuses::add);
      } catch (IllegalArgumentException e) {
        throw ApiProblem.badRequest("validation", "unknown status", List.of(new ApiProblem.FieldError("status", status)));
      }
    }
    OrderQueries.Page page;
    try {
      page = queries.list(caller.id(request), statuses, cursor, limit);
    } catch (RuntimeException e) {
      throw ApiProblem.badRequest("validation", "invalid cursor", List.of(new ApiProblem.FieldError("cursor", "invalid")));
    }
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("items", page.items().stream().map(v -> new SummaryJson(v.orderId(), v.status().name(), MoneyJson.of(v.total()),
        v.itemCount(), v.placedAt(), v.version())).toList());
    body.put("nextCursor", page.nextCursor());
    return body;
  }

  static OrderJson json(OrderView v) {
    return new OrderJson(v.orderId(), v.status().name(), MoneyJson.of(v.total()), v.itemCount(), v.placedAt(), v.version(),
        v.lines().stream().map(l -> new LineJson(l.lineId(), l.sku(), l.productName(), l.quantity(), MoneyJson.of(l.unitPrice()),
            MoneyJson.of(l.lineTotal()), l.returnedQuantity())).toList(),
        v.cancellationReason(), v.shipment() == null ? null : new ShipmentJson(v.shipment().carrier(), v.shipment().trackingNumber(),
            v.shipment().status() == null ? "UNKNOWN" : v.shipment().status()),
        v.invoiceAvailable(), MoneyJson.of(v.refundedTotal()),
        v.timeline().stream().map(t -> new TimelineJson(t.at(), t.kind(), t.description() == null ? t.kind() : t.description(), t.eventId())).toList(),
        v.source().name());
  }
}
