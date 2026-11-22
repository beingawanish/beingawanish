package com.edacommerce.edacommon.testing;

import com.edacommerce.common.ClaimCheck;
import com.edacommerce.edacommon.claimcheck.ClaimCheckStore;
import com.edacommerce.edacommon.claimcheck.ClaimChecks;
import com.edacommerce.edacommon.errors.RetryLaterException;
import java.net.MalformedURLException;
import java.net.URI;
import java.net.URL;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.lang.Nullable;

/** Claim-check store in memory, with the same verification rules as the S3 store. */
public class InMemoryClaimCheckStore implements ClaimCheckStore {
  private final Map<String, byte[]> objects = new ConcurrentHashMap<>();

  @Override
  public ClaimCheck put(
      String bucket, String key, byte[] bytes, String contentType, @Nullable Instant expiresAt) {
    objects.put(bucket + "/" + key, bytes.clone());
    return ClaimChecks.of(bucket, key, bytes, contentType, expiresAt);
  }

  @Override
  public byte[] get(ClaimCheck claimCheck) {
    byte[] bytes = objects.get(claimCheck.getBucket() + "/" + claimCheck.getObjectKey());
    if (bytes == null) {
      throw new RetryLaterException("claim-check object not found: " + claimCheck.getObjectKey());
    }
    return ClaimChecks.verify(claimCheck, bytes);
  }

  @Override
  public URL presign(ClaimCheck claimCheck, Duration ttl) {
    try {
      return URI.create(
              "http://claimcheck.test/"
                  + claimCheck.getBucket()
                  + "/"
                  + claimCheck.getObjectKey()
                  + "?X-Amz-Expires="
                  + ttl.toSeconds())
          .toURL();
    } catch (MalformedURLException e) {
      throw new IllegalStateException(e);
    }
  }

  public Map<String, byte[]> objects() {
    return Map.copyOf(objects);
  }

  public void corrupt(String bucket, String key) {
    objects.computeIfPresent(bucket + "/" + key, (k, v) -> new byte[] {1, 2, 3});
  }
}
