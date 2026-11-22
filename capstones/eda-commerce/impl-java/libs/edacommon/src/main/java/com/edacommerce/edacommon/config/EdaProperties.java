package com.edacommerce.edacommon.config;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Typed view of the configuration contract (guide §7). The environment variables are mapped onto
 * {@code eda.*} by {@link EdaEnvironmentPostProcessor}, so this class is the only place code reads them.
 */
@ConfigurationProperties(prefix = "eda")
public class EdaProperties {

  public enum OutboxRelay {
    DEBEZIUM,
    POLLING
  }

  public enum AuthMode {
    NONE,
    OIDC
  }

  private String serviceName = "unknown-svc";
  private String environment = "local";
  private String impl = "java";
  private String consumerGroup;
  private OutboxRelay outboxRelay = OutboxRelay.DEBEZIUM;
  private Duration outboxPollInterval = Duration.ofMillis(200);
  private String schemaRegistryUrl = "http://localhost:8081";
  private final Kafka kafka = new Kafka();
  private final S3 s3 = new S3();
  private final Auth auth = new Auth();
  private final Consumer consumer = new Consumer();
  private final Idempotency idempotency = new Idempotency();

  public String getServiceName() {
    return serviceName;
  }

  public void setServiceName(String serviceName) {
    this.serviceName = serviceName;
  }

  public String getEnvironment() {
    return environment;
  }

  public void setEnvironment(String environment) {
    this.environment = environment;
  }

  public String getImpl() {
    return impl;
  }

  public void setImpl(String impl) {
    this.impl = impl;
  }

  /** CONSUMER_GROUP; defaults to the service name (guide §6.1). */
  public String getConsumerGroup() {
    return consumerGroup == null || consumerGroup.isBlank() ? serviceName : consumerGroup;
  }

  public void setConsumerGroup(String consumerGroup) {
    this.consumerGroup = consumerGroup;
  }

  public OutboxRelay getOutboxRelay() {
    return outboxRelay;
  }

  public void setOutboxRelay(OutboxRelay outboxRelay) {
    this.outboxRelay = outboxRelay;
  }

  public Duration getOutboxPollInterval() {
    return outboxPollInterval;
  }

  public void setOutboxPollInterval(Duration outboxPollInterval) {
    this.outboxPollInterval = outboxPollInterval;
  }

  public String getSchemaRegistryUrl() {
    return schemaRegistryUrl;
  }

  public void setSchemaRegistryUrl(String schemaRegistryUrl) {
    this.schemaRegistryUrl = schemaRegistryUrl;
  }

  public Kafka getKafka() {
    return kafka;
  }

  public S3 getS3() {
    return s3;
  }

  public Auth getAuth() {
    return auth;
  }

  public Consumer getConsumer() {
    return consumer;
  }

  public Idempotency getIdempotency() {
    return idempotency;
  }

  public boolean isLocal() {
    return "local".equalsIgnoreCase(environment);
  }

  /** Kafka connection settings (KAFKA_*). */
  public static class Kafka {
    private String bootstrapServers = "localhost:9092";
    private String securityProtocol = "PLAINTEXT";
    private String sslCaLocation;
    private String sslCertLocation;
    private String sslKeyLocation;
    private String groupInstanceId;

    public String getBootstrapServers() {
      return bootstrapServers;
    }

    public void setBootstrapServers(String bootstrapServers) {
      this.bootstrapServers = bootstrapServers;
    }

    public String getSecurityProtocol() {
      return securityProtocol;
    }

    public void setSecurityProtocol(String securityProtocol) {
      this.securityProtocol = securityProtocol;
    }

    public String getSslCaLocation() {
      return sslCaLocation;
    }

    public void setSslCaLocation(String sslCaLocation) {
      this.sslCaLocation = sslCaLocation;
    }

    public String getSslCertLocation() {
      return sslCertLocation;
    }

    public void setSslCertLocation(String sslCertLocation) {
      this.sslCertLocation = sslCertLocation;
    }

    public String getSslKeyLocation() {
      return sslKeyLocation;
    }

    public void setSslKeyLocation(String sslKeyLocation) {
      this.sslKeyLocation = sslKeyLocation;
    }

    /** Static membership (guide §7.1): the pod name in Kubernetes (POD_NAME), unset locally. */
    public String getGroupInstanceId() {
      return groupInstanceId;
    }

    public void setGroupInstanceId(String groupInstanceId) {
      this.groupInstanceId = groupInstanceId;
    }
  }

  /** Object storage for claim checks (S3_*). */
  public static class S3 {
    private String endpoint = "http://localhost:9000";
    private String region = "us-east-1";
    private String accessKey = "claimcheck";
    private String secretKey = "claimcheck-secret";

    public String getEndpoint() {
      return endpoint;
    }

    public void setEndpoint(String endpoint) {
      this.endpoint = endpoint;
    }

    public String getRegion() {
      return region;
    }

    public void setRegion(String region) {
      this.region = region;
    }

    public String getAccessKey() {
      return accessKey;
    }

    public void setAccessKey(String accessKey) {
      this.accessKey = accessKey;
    }

    public String getSecretKey() {
      return secretKey;
    }

    public void setSecretKey(String secretKey) {
      this.secretKey = secretKey;
    }
  }

  /** Edge authentication (AUTH_MODE, OIDC_*), ADR-0013. */
  public static class Auth {
    private AuthMode mode = AuthMode.NONE;
    private String issuerUrl = "http://localhost:8180/realms/edacommerce";
    private String audience = "edacommerce-api";

    public AuthMode getMode() {
      return mode;
    }

    public void setMode(AuthMode mode) {
      this.mode = mode;
    }

    public String getIssuerUrl() {
      return issuerUrl;
    }

    public void setIssuerUrl(String issuerUrl) {
      this.issuerUrl = issuerUrl;
    }

    public String getAudience() {
      return audience;
    }

    public void setAudience(String audience) {
      this.audience = audience;
    }
  }

  /** Consumer runtime settings. Topics are declared by each service in its application.yml. */
  public static class Consumer {
    private boolean enabled = true;
    private List<String> topics = new ArrayList<>();
    private int concurrency = 3;
    private int retryConcurrency = 1;
    private Duration shutdownTimeout = Duration.ofSeconds(30);

    public boolean isEnabled() {
      return enabled;
    }

    public void setEnabled(boolean enabled) {
      this.enabled = enabled;
    }

    public List<String> getTopics() {
      return topics;
    }

    public void setTopics(List<String> topics) {
      this.topics = topics;
    }

    public int getConcurrency() {
      return concurrency;
    }

    public void setConcurrency(int concurrency) {
      this.concurrency = concurrency;
    }

    public int getRetryConcurrency() {
      return retryConcurrency;
    }

    public void setRetryConcurrency(int retryConcurrency) {
      this.retryConcurrency = retryConcurrency;
    }

    public Duration getShutdownTimeout() {
      return shutdownTimeout;
    }

    public void setShutdownTimeout(Duration shutdownTimeout) {
      this.shutdownTimeout = shutdownTimeout;
    }
  }

  /** Paths whose POST requires an Idempotency-Key (ADR-0012). */
  public static class Idempotency {
    private List<String> paths =
        new ArrayList<>(List.of("/ops/dlq/replay", "/ops/sagas/*/retry-step"));
    private Duration ttl = Duration.ofHours(24);

    public List<String> getPaths() {
      return paths;
    }

    public void setPaths(List<String> paths) {
      this.paths = paths;
    }

    public Duration getTtl() {
      return ttl;
    }

    public void setTtl(Duration ttl) {
      this.ttl = ttl;
    }
  }
}
