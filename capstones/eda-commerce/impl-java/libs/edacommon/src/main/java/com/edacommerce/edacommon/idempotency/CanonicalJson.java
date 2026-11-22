package com.edacommerce.edacommon.idempotency;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.json.JsonMapper;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/**
 * Canonical JSON and the request hash for Idempotency-Key handling (guide §5 rule 14, ADR-0012):
 * sorted keys, no insignificant whitespace, UTF-8, numbers as parsed. The hash is
 * {@code hex(SHA-256(METHOD + "\n" + path + "\n" + canonicalJson(body)))}; an empty body
 * canonicalises to the empty string.
 */
public final class CanonicalJson {
  private CanonicalJson() {}

  private static final ObjectMapper MAPPER =
      JsonMapper.builder()
          .configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS, true)
          .configure(com.fasterxml.jackson.databind.MapperFeature.SORT_PROPERTIES_ALPHABETICALLY, true)
          .build();

  public static String canonicalise(byte[] body) {
    if (body == null || body.length == 0 || new String(body, StandardCharsets.UTF_8).isBlank()) {
      return "";
    }
    try {
      Object value = MAPPER.readValue(body, Object.class);
      return MAPPER.writeValueAsString(value);
    } catch (IOException e) {
      // Not JSON: hash the raw bytes; the endpoint itself will reject the body.
      return new String(body, StandardCharsets.UTF_8);
    }
  }

  public static String requestHash(String method, String path, byte[] body) {
    String material = method.toUpperCase(java.util.Locale.ROOT) + "\n" + path + "\n" + canonicalise(body);
    try {
      byte[] digest =
          MessageDigest.getInstance("SHA-256").digest(material.getBytes(StandardCharsets.UTF_8));
      return HexFormat.of().formatHex(digest);
    } catch (NoSuchAlgorithmException e) {
      throw new IllegalStateException(e);
    }
  }
}
