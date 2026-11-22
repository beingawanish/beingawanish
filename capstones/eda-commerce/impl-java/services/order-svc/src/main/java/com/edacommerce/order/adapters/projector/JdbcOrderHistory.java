package com.edacommerce.order.adapters.projector;

import com.edacommerce.kernel.Money;
import com.edacommerce.order.application.OrderHistoryReadModel;
import com.edacommerce.order.application.OrderView;
import com.edacommerce.order.domain.OrderStatus;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * The order-history projection in schema {@code order_history} (ADR-0010): writes for the projector,
 * reads for the Orders API. Order-event updates are guarded by aggregateVersion (stale versions are
 * dropped); timeline rows are keyed by eventId, so replays and duplicates are no-ops.
 */
@Component
public class JdbcOrderHistory implements OrderHistoryReadModel {
  private final JdbcTemplate jdbc;

  public JdbcOrderHistory(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  // ------------------------------------------------------------------ writes (projector)

  /** Inserts the summary and lines of a new order; false if this version is not newer. */
  public boolean placed(String orderId, String customerId, Money total, int itemCount, Instant placedAt, long version, List<OrderView.Line> lines) {
    int n = jdbc.update(
        "INSERT INTO order_history.order_summary (order_id, customer_id, status, total_minor, currency, item_count, placed_at, version,"
            + " refunded_minor) VALUES (?, ?, 'PENDING', ?, ?, ?, ?, ?, 0) ON CONFLICT (order_id) DO NOTHING",
        orderId, customerId, total.amountMinor(), total.currency(), itemCount, Timestamp.from(placedAt), version);
    if (n == 1) {
      for (OrderView.Line l : lines) {
        jdbc.update("INSERT INTO order_history.order_line (order_id, line_id, sku, product_name, quantity, unit_price_minor, line_total_minor,"
                + " currency) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            orderId, l.lineId(), l.sku(), l.productName(), l.quantity(), l.unitPrice().amountMinor(), l.lineTotal().amountMinor(),
            l.unitPrice().currency());
      }
    }
    return n == 1;
  }

  public boolean exists(String orderId) {
    Integer n = jdbc.queryForObject("SELECT count(*) FROM order_history.order_summary WHERE order_id = ?", Integer.class, orderId);
    return n != null && n > 0;
  }

  /** Version-guarded status change from an order event. Returns false when stale. */
  public boolean orderEvent(String orderId, long version, OrderStatus status, String cancellationReason, String carrier,
      String trackingNumber, Boolean invoiceAvailable) {
    return jdbc.update(
        "UPDATE order_history.order_summary SET version = ?, status = coalesce(?::text, status),"
            + " cancellation_reason = coalesce(?::text, cancellation_reason), carrier = coalesce(?::text, carrier),"
            + " tracking_number = coalesce(?::text, tracking_number), shipment_status = CASE WHEN ?::text IS NOT NULL THEN 'SHIPPED' ELSE shipment_status END,"
            + " invoice_available = coalesce(?::boolean, invoice_available), updated_at = now() WHERE order_id = ? AND version < ?",
        version, status == null ? null : status.name(), cancellationReason, carrier, trackingNumber, carrier, invoiceAvailable,
        orderId, version) == 1;
  }

  /** Adds a timeline entry; false when this event was already projected. */
  public boolean timeline(String eventId, String orderId, Instant at, String kind, String description) {
    return jdbc.update("INSERT INTO order_history.timeline (event_id, order_id, at, kind, description) VALUES (?, ?, ?, ?, ?)"
        + " ON CONFLICT (event_id) DO NOTHING", eventId, orderId, Timestamp.from(at), kind, description) == 1;
  }

  public void refunded(String orderId, long amountMinor) {
    jdbc.update("UPDATE order_history.order_summary SET refunded_minor = refunded_minor + ? WHERE order_id = ?", amountMinor, orderId);
  }

  /** Carrier progress only moves forward. */
  public void shipmentStatus(String orderId, String status, int rank) {
    jdbc.update("UPDATE order_history.order_summary SET shipment_status = ?, shipment_rank = ? WHERE order_id = ? AND shipment_rank < ?",
        status, rank, orderId, rank);
  }

  /** Return progress (a different aggregate, so not version-guarded on the order's version). */
  public void returnStatus(String orderId, OrderStatus status, boolean onlyIfDelivered) {
    jdbc.update("UPDATE order_history.order_summary SET status = ? WHERE order_id = ?"
        + (onlyIfDelivered ? " AND status IN ('DELIVERED', 'RETURN_IN_PROGRESS', 'PARTIALLY_RETURNED')" : ""), status.name(), orderId);
  }

  // ------------------------------------------------------------------ reads (API)

  @Override
  public Optional<OrderView> find(String orderId) {
    List<OrderView> rows = jdbc.query("SELECT * FROM order_history.order_summary WHERE order_id = ?", (rs, i) -> summary(rs, true), orderId);
    return rows.stream().findFirst();
  }

  @Override
  public List<OrderView> listForCustomer(String customerId, Set<OrderStatus> statuses, Instant beforePlacedAt, String beforeOrderId, int limit) {
    StringBuilder sql = new StringBuilder("SELECT * FROM order_history.order_summary WHERE customer_id = ?");
    List<Object> args = new ArrayList<>(List.of(customerId));
    if (!statuses.isEmpty()) {
      sql.append(" AND status = ANY (?)");
      args.add(statuses.stream().map(Enum::name).toArray(String[]::new));
    }
    if (beforePlacedAt != null) {
      sql.append(" AND (placed_at, order_id) < (?, ?)");
      args.add(Timestamp.from(beforePlacedAt));
      args.add(beforeOrderId);
    }
    sql.append(" ORDER BY placed_at DESC, order_id DESC LIMIT ?");
    args.add(limit);
    return jdbc.query(sql.toString(), (rs, i) -> summary(rs, false), args.toArray());
  }

  private OrderView summary(ResultSet rs, boolean details) throws SQLException {
    String id = rs.getString("order_id");
    String currency = rs.getString("currency");
    List<OrderView.Line> lines = List.of();
    List<OrderView.TimelineEntry> timeline = List.of();
    if (details) {
      lines = jdbc.query("SELECT * FROM order_history.order_line WHERE order_id = ? ORDER BY line_id", (r, i) -> new OrderView.Line(
          r.getString("line_id"), r.getString("sku"), r.getString("product_name"), r.getInt("quantity"),
          Money.of(r.getLong("unit_price_minor"), currency), Money.of(r.getLong("line_total_minor"), currency), r.getInt("returned_quantity")), id);
      timeline = jdbc.query("SELECT * FROM order_history.timeline WHERE order_id = ? ORDER BY at, event_id", (r, i) -> new OrderView.TimelineEntry(
          r.getTimestamp("at").toInstant(), r.getString("kind"), r.getString("description"), r.getString("event_id")), id);
    }
    String carrier = rs.getString("carrier");
    return new OrderView(id, rs.getString("customer_id"), OrderStatus.valueOf(rs.getString("status")),
        Money.of(rs.getLong("total_minor"), currency), rs.getInt("item_count"), rs.getTimestamp("placed_at").toInstant(),
        rs.getLong("version"), lines, rs.getString("cancellation_reason"),
        carrier == null ? null : new OrderView.Shipment(carrier, rs.getString("tracking_number"), rs.getString("shipment_status")),
        rs.getBoolean("invoice_available"), Money.of(rs.getLong("refunded_minor"), currency), timeline, OrderView.Source.READ_MODEL);
  }
}
