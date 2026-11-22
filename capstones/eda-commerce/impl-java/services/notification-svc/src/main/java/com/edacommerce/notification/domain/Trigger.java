package com.edacommerce.notification.domain;

import java.time.Instant;

/**
 * The facts notification-svc reacts to (choreography, ADR-0001): producers do not know it exists.
 * Each names the business id that makes it unique, so a fact re-emitted with a new eventId is
 * recognised as the same fact.
 */
public sealed interface Trigger {
  String orderId();

  /** Business identity of the fact (with the template, the dedupe key). */
  String subjectId();

  record OrderConfirmed(String orderId) implements Trigger {
    @Override
    public String subjectId() {
      return orderId;
    }
  }

  record OrderCancelled(String orderId, String reason) implements Trigger {
    @Override
    public String subjectId() {
      return orderId;
    }
  }

  record OrderShipped(String orderId, String shipmentId, String carrier, String trackingNumber)
      implements Trigger {
    @Override
    public String subjectId() {
      return shipmentId;
    }
  }

  record InvoiceIssued(String orderId, String invoiceId, String invoiceNumber) implements Trigger {
    @Override
    public String subjectId() {
      return invoiceId;
    }
  }

  record OrderDelivered(String orderId, Instant returnWindowEndsAt) implements Trigger {
    @Override
    public String subjectId() {
      return orderId;
    }
  }

  /**
   * @param outbound false for return shipments
   */
  record ShipmentProblem(String orderId, String shipmentId, boolean outbound, String code)
      implements Trigger {
    @Override
    public String subjectId() {
      return shipmentId + ":" + code;
    }
  }

  record ReturnLabelIssued(
      String orderId, String returnId, String shipmentId, String trackingNumber)
      implements Trigger {
    @Override
    public String subjectId() {
      return shipmentId;
    }
  }

  record ReturnAuthorized(String orderId, String returnId, String rmaNumber, Instant parcelDueBy)
      implements Trigger {
    @Override
    public String subjectId() {
      return returnId;
    }
  }

  record ReturnRejected(String orderId, String returnId, String reason) implements Trigger {
    @Override
    public String subjectId() {
      return returnId;
    }
  }

  record ReturnRefunded(String orderId, String returnId, long amountMinor, String currency)
      implements Trigger {
    @Override
    public String subjectId() {
      return returnId;
    }
  }

  /**
   * @param outcome ReturnClosed.outcome
   */
  record ReturnClosed(String orderId, String returnId, String outcome) implements Trigger {
    @Override
    public String subjectId() {
      return returnId;
    }
  }
}
