package com.edacommerce.shipping.application;

import com.edacommerce.common.Address;
import com.edacommerce.common.ClaimCheck;
import com.edacommerce.common.ShipmentDirection;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.shipping.ShipmentCreated;
import com.edacommerce.shipping.ShipmentDelivered;
import com.edacommerce.shipping.ShipmentException;
import com.edacommerce.shipping.ShipmentExceptionCode;
import com.edacommerce.shipping.ShipmentInTransit;
import com.edacommerce.shipping.domain.DocumentRef;
import com.edacommerce.shipping.domain.PostalAddress;
import com.edacommerce.shipping.domain.Shipment;
import com.edacommerce.shipping.domain.ShipmentEvent;
import org.apache.avro.specific.SpecificRecord;

/** Domain facts -> contract messages on shipping.events.v1, keyed by orderId (ADR-0005). */
public final class ShippingMessages {
  private ShippingMessages() {}

  public static final String EVENTS = "shipping.events.v1";

  public static OutgoingMessage event(Shipment s, ShipmentEvent e) {
    ShipmentDirection direction = ShipmentDirection.valueOf(s.direction().name());
    SpecificRecord record =
        switch (e) {
          case ShipmentEvent.Created x ->
              ShipmentCreated.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(s.orderId())
                  .setShipmentId(s.shipmentId())
                  .setDirection(direction)
                  .setFulfilmentId(s.fulfilmentId())
                  .setReturnId(s.returnId())
                  .setCarrier(s.carrier())
                  .setTrackingNumber(s.trackingNumber())
                  .setLabel(claimCheck(s.label()))
                  .setCreatedAt(s.bookedAt())
                  .build();
          case ShipmentEvent.InTransit x ->
              ShipmentInTransit.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(s.orderId())
                  .setShipmentId(s.shipmentId())
                  .setDirection(direction)
                  .setLocation(x.location())
                  .setCarrierEventId(x.carrierEventId())
                  .setCarrierTimestamp(x.carrierTimestamp())
                  .build();
          case ShipmentEvent.Delivered x ->
              ShipmentDelivered.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(s.orderId())
                  .setShipmentId(s.shipmentId())
                  .setDirection(direction)
                  .setReturnId(s.returnId())
                  .setCarrierEventId(x.carrierEventId())
                  .setDeliveredAt(x.deliveredAt())
                  .build();
          case ShipmentEvent.Problem x ->
              ShipmentException.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(s.orderId())
                  .setShipmentId(s.shipmentId())
                  .setDirection(direction)
                  .setCode(ShipmentExceptionCode.valueOf(x.code()))
                  .setDetail(x.detail())
                  .setCarrierEventId(x.carrierEventId())
                  .setRaisedAt(x.raisedAt())
                  .build();
        };
    return OutgoingMessage.of(EVENTS, s.orderId(), record, "Shipment", s.shipmentId(), e.version());
  }

  public static ClaimCheck claimCheck(DocumentRef d) {
    return ClaimCheck.newBuilder()
        .setStore("s3")
        .setBucket(d.bucket())
        .setObjectKey(d.objectKey())
        .setContentType(d.contentType())
        .setSizeBytes(d.sizeBytes())
        .setSha256(d.sha256())
        .setExpiresAt(d.expiresAt())
        .build();
  }

  public static DocumentRef documentRef(ClaimCheck c) {
    return new DocumentRef(
        c.getBucket(),
        c.getObjectKey(),
        c.getContentType(),
        c.getSizeBytes(),
        c.getSha256(),
        c.getExpiresAt());
  }

  public static PostalAddress address(Address a) {
    return new PostalAddress(
        a.getRecipientName(),
        a.getLine1(),
        a.getLine2(),
        a.getCity(),
        a.getRegion(),
        a.getPostalCode(),
        a.getCountryCode(),
        a.getPhone());
  }
}
