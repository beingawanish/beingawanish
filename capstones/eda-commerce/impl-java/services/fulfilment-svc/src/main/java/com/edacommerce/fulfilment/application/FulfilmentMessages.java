package com.edacommerce.fulfilment.application;

import com.edacommerce.common.Address;
import com.edacommerce.common.ClaimCheck;
import com.edacommerce.common.ShippingMethod;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.fulfilment.FulfilmentAccepted;
import com.edacommerce.fulfilment.FulfilmentCancelled;
import com.edacommerce.fulfilment.FulfilmentFailed;
import com.edacommerce.fulfilment.FulfilmentFailureReason;
import com.edacommerce.fulfilment.OrderDispatched;
import com.edacommerce.fulfilment.OrderPacked;
import com.edacommerce.fulfilment.OrderPicked;
import com.edacommerce.fulfilment.ReturnInspected;
import com.edacommerce.fulfilment.ReturnReceived;
import com.edacommerce.fulfilment.domain.DocumentRef;
import com.edacommerce.fulfilment.domain.Fulfilment;
import com.edacommerce.fulfilment.domain.FulfilmentEvent;
import com.edacommerce.fulfilment.domain.ReturnIntake;
import com.edacommerce.fulfilment.domain.ShipTo;
import org.apache.avro.specific.SpecificRecord;

/** Domain facts -> contract messages on fulfilment.events.v1, keyed by orderId (ADR-0005). */
public final class FulfilmentMessages {
  private FulfilmentMessages() {}

  public static final String EVENTS = "fulfilment.events.v1";

  public static OutgoingMessage event(Fulfilment f, FulfilmentEvent e) {
    SpecificRecord record =
        switch (e) {
          case FulfilmentEvent.Accepted x ->
              FulfilmentAccepted.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(f.orderId())
                  .setFulfilmentId(f.fulfilmentId())
                  .setWarehouseId(f.warehouseId())
                  .setAcceptedAt(f.acceptedAt())
                  .setEstimatedDispatchAt(f.estimatedDispatchAt())
                  .build();
          case FulfilmentEvent.Picked x ->
              OrderPicked.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(f.orderId())
                  .setFulfilmentId(f.fulfilmentId())
                  .setPickedAt(f.pickedAt())
                  .build();
          case FulfilmentEvent.Packed x ->
              OrderPacked.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(f.orderId())
                  .setFulfilmentId(f.fulfilmentId())
                  .setWarehouseId(f.warehouseId())
                  .setParcels(
                      f.parcels().stream()
                          .map(
                              p ->
                                  new com.edacommerce.fulfilment.Parcel(
                                      p.parcelId(),
                                      p.weightGrams(),
                                      p.lengthMm(),
                                      p.widthMm(),
                                      p.heightMm()))
                          .toList())
                  .setManifest(claimCheck(f.manifest()))
                  .setShipTo(address(f.shipTo()))
                  .setShippingMethod(shippingMethod(f.shippingMethod()))
                  .setPackedAt(f.packedAt())
                  .build();
          case FulfilmentEvent.Dispatched x ->
              OrderDispatched.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(f.orderId())
                  .setFulfilmentId(f.fulfilmentId())
                  .setShipmentId(f.shipmentId())
                  .setDispatchedAt(f.dispatchedAt())
                  .build();
          case FulfilmentEvent.Cancelled x ->
              FulfilmentCancelled.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(f.orderId())
                  .setFulfilmentId(f.fulfilmentId())
                  .setCancelledAt(f.cancelledAt())
                  .build();
          case FulfilmentEvent.Failed x ->
              FulfilmentFailed.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(f.orderId())
                  .setFulfilmentId(f.fulfilmentId())
                  .setReason(FulfilmentFailureReason.valueOf(f.failureReason().name()))
                  .setDetail(f.failureDetail())
                  .setFailedAt(f.failedAt())
                  .build();
        };
    return OutgoingMessage.of(
        EVENTS, f.orderId(), record, "Fulfilment", f.fulfilmentId(), e.version());
  }

  public static OutgoingMessage returnReceived(ReturnIntake r, long version) {
    ReturnReceived e =
        ReturnReceived.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(r.orderId())
            .setReturnId(r.returnId())
            .setReceivedAt(r.receivedAt())
            .build();
    return OutgoingMessage.of(EVENTS, r.orderId(), e, "ReturnIntake", r.returnId(), version);
  }

  public static OutgoingMessage returnInspected(ReturnIntake r, long version) {
    ReturnInspected e =
        ReturnInspected.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(r.orderId())
            .setReturnId(r.returnId())
            .setResults(
                r.results().stream()
                    .map(
                        x ->
                            new com.edacommerce.fulfilment.InspectionResult(
                                x.lineId(),
                                x.sku(),
                                x.quantity(),
                                com.edacommerce.fulfilment.InspectionOutcome.valueOf(
                                    x.outcome().name()),
                                x.note()))
                    .toList())
            .setInspectedAt(r.inspectedAt())
            .build();
    return OutgoingMessage.of(EVENTS, r.orderId(), e, "ReturnIntake", r.returnId(), version);
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

  public static Address address(ShipTo a) {
    return Address.newBuilder()
        .setRecipientName(a.recipientName())
        .setLine1(a.line1())
        .setLine2(a.line2())
        .setCity(a.city())
        .setRegion(a.region())
        .setPostalCode(a.postalCode())
        .setCountryCode(a.countryCode())
        .setPhone(a.phone())
        .build();
  }

  public static ShipTo shipTo(Address a) {
    return new ShipTo(
        a.getRecipientName(),
        a.getLine1(),
        a.getLine2(),
        a.getCity(),
        a.getRegion(),
        a.getPostalCode(),
        a.getCountryCode(),
        a.getPhone());
  }

  static ShippingMethod shippingMethod(String method) {
    for (ShippingMethod m : ShippingMethod.values()) {
      if (m.name().equals(method)) {
        return m;
      }
    }
    return ShippingMethod.UNKNOWN;
  }
}
