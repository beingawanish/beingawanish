package com.edacommerce.fulfilment.domain;

import java.time.Instant;

/** Where the packing manifest is stored (the claim check of ADR-0009, as a domain value). */
public record DocumentRef(
    String bucket,
    String objectKey,
    String contentType,
    long sizeBytes,
    String sha256,
    Instant expiresAt) {}
