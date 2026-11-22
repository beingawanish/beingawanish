package com.edacommerce.edacommon.claimcheck;

import com.edacommerce.common.ClaimCheck;
import com.edacommerce.edacommon.config.EdaProperties;
import com.edacommerce.edacommon.errors.RetryLaterException;
import com.edacommerce.edacommon.errors.TransientException;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import java.net.URI;
import java.net.URL;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import org.springframework.lang.Nullable;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.core.exception.SdkClientException;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.S3Configuration;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.NoSuchKeyException;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import software.amazon.awssdk.services.s3.model.S3Exception;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;

/**
 * Claim checks on S3-compatible storage (MinIO locally): AWS SDK v2 with endpoint override and
 * path-style access. Infrastructure errors are classified here, once (guide §6.3): connection
 * problems and 5xx are Transient, a missing object is RetryLater.
 */
public class S3ClaimCheckStore implements ClaimCheckStore {
  private final S3Client s3;
  private final S3Presigner presigner;
  private final EdaMetrics metrics;
  private final Clock clock;

  public S3ClaimCheckStore(S3Client s3, S3Presigner presigner, EdaMetrics metrics, Clock clock) {
    this.s3 = s3;
    this.presigner = presigner;
    this.metrics = metrics;
    this.clock = clock;
  }

  public static S3ClaimCheckStore fromProperties(
      EdaProperties.S3 p, EdaMetrics metrics, Clock clock) {
    var credentials =
        StaticCredentialsProvider.create(
            AwsBasicCredentials.create(p.getAccessKey(), p.getSecretKey()));
    S3Configuration pathStyle = S3Configuration.builder().pathStyleAccessEnabled(true).build();
    S3Client client =
        S3Client.builder()
            .endpointOverride(URI.create(p.getEndpoint()))
            .region(Region.of(p.getRegion()))
            .credentialsProvider(credentials)
            .serviceConfiguration(pathStyle)
            .build();
    S3Presigner presigner =
        S3Presigner.builder()
            .endpointOverride(URI.create(p.getEndpoint()))
            .region(Region.of(p.getRegion()))
            .credentialsProvider(credentials)
            .serviceConfiguration(pathStyle)
            .build();
    return new S3ClaimCheckStore(client, presigner, metrics, clock);
  }

  @Override
  public ClaimCheck put(
      String bucket, String key, byte[] bytes, String contentType, @Nullable Instant expiresAt) {
    ClaimCheck claimCheck = ClaimChecks.of(bucket, key, bytes, contentType, expiresAt);
    try {
      s3.putObject(
          PutObjectRequest.builder().bucket(bucket).key(key).contentType(contentType).build(),
          RequestBody.fromBytes(bytes));
    } catch (SdkClientException e) {
      throw new TransientException("object storage unreachable: " + e.getMessage(), e);
    } catch (S3Exception e) {
      throw classify(e, key);
    }
    metrics.claimCheckSize(bucket, "put", bytes.length);
    return claimCheck;
  }

  @Override
  public byte[] get(ClaimCheck claimCheck) {
    Instant expiresAt = claimCheck.getExpiresAt();
    if (expiresAt != null && clock.instant().isAfter(expiresAt)) {
      throw new ClaimCheckExpiredException("claim check expired: " + claimCheck.getObjectKey());
    }
    byte[] bytes;
    try {
      bytes =
          s3.getObjectAsBytes(
                  GetObjectRequest.builder()
                      .bucket(claimCheck.getBucket())
                      .key(claimCheck.getObjectKey())
                      .build())
              .asByteArray();
    } catch (NoSuchKeyException e) {
      throw new RetryLaterException(
          "claim-check object not found: " + claimCheck.getObjectKey(), e);
    } catch (SdkClientException e) {
      throw new TransientException("object storage unreachable: " + e.getMessage(), e);
    } catch (S3Exception e) {
      throw classify(e, claimCheck.getObjectKey());
    }
    metrics.claimCheckSize(claimCheck.getBucket(), "get", bytes.length);
    return ClaimChecks.verify(claimCheck, bytes);
  }

  @Override
  public URL presign(ClaimCheck claimCheck, Duration ttl) {
    return presigner
        .presignGetObject(
            r ->
                r.signatureDuration(ttl)
                    .getObjectRequest(
                        g -> g.bucket(claimCheck.getBucket()).key(claimCheck.getObjectKey())))
        .url();
  }

  private static RuntimeException classify(S3Exception e, String key) {
    if (e.statusCode() == 404) {
      return new RetryLaterException("claim-check object not found: " + key, e);
    }
    if (e.statusCode() >= 500 || e.statusCode() == 429) {
      return new TransientException("object storage answered " + e.statusCode(), e);
    }
    return new RetryLaterException(
        "object storage refused " + key + " (" + e.statusCode() + ")", e);
  }
}
