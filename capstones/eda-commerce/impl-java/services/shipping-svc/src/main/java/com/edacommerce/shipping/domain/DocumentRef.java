package com.edacommerce.shipping.domain;

import java.time.Instant;

/** Where the label PDF is stored (the claim check of ADR-0009, as a domain value). */
public record DocumentRef(
    String bucket,
    String objectKey,
    String contentType,
    long sizeBytes,
    String sha256,
    Instant expiresAt) {}
