package com.edacommerce.notification.domain;

import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Locale;
import java.util.Optional;

/**
 * Which fact gets which message, and what it says. Pure. Facts that need no message (a return
 * closed as REFUNDED, already announced by ReturnRefunded; an outbound booking failure, which is an
 * operations matter) map to nothing.
 */
public final class NotificationPolicy {
  private NotificationPolicy() {}

  private static final DateTimeFormatter DATE =
      DateTimeFormatter.ofPattern("d MMMM yyyy", Locale.ENGLISH).withZone(ZoneOffset.UTC);

  /** A message to send. {@code attachmentWanted}: the fact carries a document to attach. */
  public record Plan(
      Template template, String dedupeKey, String subject, String body, boolean attachmentWanted) {}

  public static Optional<Plan> react(Trigger t, String name) {
    String hello = "Hello " + name + ",\n\n";
    return switch (t) {
      case Trigger.OrderConfirmed x ->
          plan(
              Template.ORDER_CONFIRMED,
              t,
              "Your order is confirmed",
              hello + "we have your order " + x.orderId() + " and are preparing it.",
              false);
      case Trigger.OrderCancelled x ->
          plan(
              Template.ORDER_CANCELLED,
              t,
              "Your order was cancelled",
              hello
                  + "we could not complete order "
                  + x.orderId()
                  + " ("
                  + humanReason(x.reason())
                  + "). You have not been charged.",
              false);
      case Trigger.OrderShipped x ->
          plan(
              Template.ORDER_SHIPPED,
              t,
              "Your order is on its way",
              hello
                  + "your parcel left with "
                  + x.carrier()
                  + ", tracking "
                  + x.trackingNumber()
                  + ".",
              false);
      case Trigger.InvoiceIssued x ->
          plan(
              Template.INVOICE,
              t,
              "Your invoice " + x.invoiceNumber(),
              hello + "your invoice " + x.invoiceNumber() + " is attached.",
              true);
      case Trigger.OrderDelivered x ->
          plan(
              Template.ORDER_DELIVERED,
              t,
              "Your order was delivered",
              hello
                  + "your order was delivered. You can return items until "
                  + DATE.format(x.returnWindowEndsAt())
                  + ".",
              false);
      case Trigger.ShipmentProblem x -> {
        if (!x.outbound() || x.code().equals("BOOKING_FAILED")) {
          yield Optional.empty();
        }
        yield plan(
            Template.SHIPMENT_PROBLEM,
            t,
            "A problem with your delivery",
            hello
                + "the carrier reported a problem with your parcel ("
                + x.code()
                + "). We are on it.",
            false);
      }
      case Trigger.ReturnLabelIssued x ->
          plan(
              Template.RETURN_LABEL,
              t,
              "Your return label",
              hello + "your return label is attached (tracking " + x.trackingNumber() + ").",
              true);
      case Trigger.ReturnAuthorized x ->
          plan(
              Template.RETURN_AUTHORIZED,
              t,
              "Return " + x.rmaNumber() + " approved",
              hello
                  + "your return "
                  + x.rmaNumber()
                  + " is approved. Please send the parcel by "
                  + DATE.format(x.parcelDueBy())
                  + ".",
              false);
      case Trigger.ReturnRejected x ->
          plan(
              Template.RETURN_REJECTED,
              t,
              "About your return",
              hello + "we could not accept your return: " + x.reason() + ".",
              false);
      case Trigger.ReturnRefunded x ->
          plan(
              Template.RETURN_REFUNDED,
              t,
              "Your refund",
              hello
                  + "we refunded "
                  + String.format(
                      Locale.ROOT,
                      "%d.%02d %s",
                      x.amountMinor() / 100,
                      x.amountMinor() % 100,
                      x.currency())
                  + ".",
              false);
      case Trigger.ReturnClosed x ->
          x.outcome().equals("EXPIRED")
              ? plan(
                  Template.RETURN_EXPIRED,
                  t,
                  "Your return has expired",
                  hello + "we did not receive your return parcel in time, so the return is closed.",
                  false)
              : Optional.empty();
    };
  }

  private static Optional<Plan> plan(
      Template template, Trigger t, String subject, String body, boolean attachment) {
    return Optional.of(
        new Plan(template, template.id() + ":" + t.subjectId(), subject, body, attachment));
  }

  static String humanReason(String reason) {
    return switch (reason) {
      case "OUT_OF_STOCK" -> "an item is out of stock";
      case "PAYMENT_DECLINED" -> "the payment was declined";
      case "RESERVATION_EXPIRED" -> "the payment took too long";
      case "FULFILMENT_FAILED" -> "the warehouse could not ship it";
      default -> "an internal problem";
    };
  }
}
