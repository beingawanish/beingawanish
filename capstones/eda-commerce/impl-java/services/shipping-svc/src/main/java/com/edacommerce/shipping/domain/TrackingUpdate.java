package com.edacommerce.shipping.domain;

import java.time.Instant;

/** One normalised carrier webhook. */
public record TrackingUpdate(
    String carrierEventId,
    String trackingNumber,
    CarrierStatus status,
    String exceptionCode,
    String location,
    Instant occurredAt) {}
