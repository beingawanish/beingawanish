package com.edacommerce.edacommon.serde;

import com.edacommerce.edacommon.errors.TransientException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.apache.avro.Schema;

/**
 * Schema Registry REST client with an id cache, implementing the Confluent lookup semantics used by
 * {@code KafkaAvroSerializer} with {@code auto.register.schemas=false, use.latest.version=false,
 * normalize.schemas=true}: {@code POST /subjects/{subject}?normalize=true} for the writer id and
 * {@code GET /schemas/ids/{id}} for reader resolution.
 */
public class HttpSchemaRegistryClient implements SchemaRegistryClient {
  private static final String CONTENT_TYPE = "application/vnd.schemaregistry.v1+json";

  private final String baseUrl;
  private final HttpClient http;
  private final ObjectMapper json = new ObjectMapper();
  private final Map<String, Integer> idsBySubjectAndSchema = new ConcurrentHashMap<>();
  private final Map<Integer, Schema> schemasById = new ConcurrentHashMap<>();
  private volatile boolean warm;

  public HttpSchemaRegistryClient(String baseUrl) {
    this.baseUrl = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
    this.http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
  }

  @Override
  public int lookupId(String subject, Schema schema) {
    String cacheKey = subject + "\u0000" + schema.toString();
    Integer cached = idsBySubjectAndSchema.get(cacheKey);
    if (cached != null) {
      return cached;
    }
    String body;
    try {
      body = json.writeValueAsString(Map.of("schemaType", "AVRO", "schema", schema.toString()));
    } catch (IOException e) {
      throw new IllegalStateException(e);
    }
    HttpRequest request =
        HttpRequest.newBuilder(
                URI.create(
                    baseUrl
                        + "/subjects/"
                        + URLEncoder.encode(subject, StandardCharsets.UTF_8)
                        + "?normalize=true&deleted=false"))
            .timeout(Duration.ofSeconds(5))
            .header("Content-Type", CONTENT_TYPE)
            .header("Accept", CONTENT_TYPE)
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build();
    JsonNode answer = send(request, subject);
    int id = answer.path("id").asInt();
    idsBySubjectAndSchema.put(cacheKey, id);
    schemasById.putIfAbsent(id, schema);
    return id;
  }

  @Override
  public Schema schemaById(int id) {
    Schema cached = schemasById.get(id);
    if (cached != null) {
      return cached;
    }
    HttpRequest request =
        HttpRequest.newBuilder(URI.create(baseUrl + "/schemas/ids/" + id))
            .timeout(Duration.ofSeconds(5))
            .header("Accept", CONTENT_TYPE)
            .GET()
            .build();
    JsonNode answer = send(request, "id " + id);
    Schema schema = new Schema.Parser().parse(answer.path("schema").asText());
    schemasById.put(id, schema);
    return schema;
  }

  @Override
  public boolean isWarm() {
    return warm;
  }

  @Override
  public boolean ping() {
    try {
      send(
          HttpRequest.newBuilder(URI.create(baseUrl + "/subjects"))
              .timeout(Duration.ofSeconds(2))
              .header("Accept", CONTENT_TYPE)
              .GET()
              .build(),
          "subjects");
      return true;
    } catch (RuntimeException e) {
      return false;
    }
  }

  private JsonNode send(HttpRequest request, String what) {
    HttpResponse<String> response;
    try {
      response = http.send(request, HttpResponse.BodyHandlers.ofString());
    } catch (IOException e) {
      throw new TransientException("schema registry unreachable: " + e.getMessage(), e);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new TransientException("interrupted calling schema registry", e);
    }
    int status = response.statusCode();
    if (status == 404) {
      warm = true;
      throw new SchemaNotRegisteredException("schema not registered: " + what);
    }
    if (status >= 500 || status == 429) {
      throw new TransientException("schema registry answered " + status + " for " + what);
    }
    if (status >= 400) {
      throw new SchemaNotRegisteredException(
          "schema registry rejected " + what + " (" + status + "): " + response.body());
    }
    warm = true;
    try {
      return json.readTree(response.body());
    } catch (IOException e) {
      throw new TransientException("unparseable schema registry answer for " + what, e);
    }
  }
}
