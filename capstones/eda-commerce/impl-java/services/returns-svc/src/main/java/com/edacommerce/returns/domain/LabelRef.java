package com.edacommerce.returns.domain;

import java.time.Instant;

/** The return label's claim check, as a domain value (shipping-svc stores the PDF). */
public record LabelRef(
    String bucket,
    String objectKey,
    String contentType,
    long sizeBytes,
    String sha256,
    Instant expiresAt) {}
