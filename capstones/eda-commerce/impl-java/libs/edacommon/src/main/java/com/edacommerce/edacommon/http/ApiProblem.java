package com.edacommerce.edacommon.http;

import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.lang.Nullable;

/**
 * A known HTTP failure, rendered as RFC 9457 problem details by {@link ProblemHandler}. The type URI
 * is {@code https://errors.edacommerce.example/<slug>} (guide §4 "http").
 */
public class ApiProblem extends RuntimeException {
  private static final long serialVersionUID = 1L;
  public static final String TYPE_BASE = "https://errors.edacommerce.example/";

  /** One entry of {@code errors[]} (common.yaml Problem). */
  public record FieldError(String field, String message) {}

  private final HttpStatus status;
  private final String slug;
  private final String title;
  private final transient List<FieldError> errors;
  private final transient Map<String, String> headers;

  public ApiProblem(
      HttpStatus status,
      String slug,
      String title,
      @Nullable String detail,
      List<FieldError> errors,
      Map<String, String> headers) {
    super(detail == null ? title : detail);
    this.status = status;
    this.slug = slug;
    this.title = title;
    this.errors = List.copyOf(errors);
    this.headers = Map.copyOf(headers);
  }

  public static ApiProblem of(HttpStatus status, String slug, String title, String detail) {
    return new ApiProblem(status, slug, title, detail, List.of(), Map.of());
  }

  public static ApiProblem notFound(String what) {
    return of(HttpStatus.NOT_FOUND, "not-found", "Not found", what + " not found");
  }

  public static ApiProblem badRequest(String slug, String detail, List<FieldError> errors) {
    return new ApiProblem(HttpStatus.BAD_REQUEST, slug, "Bad request", detail, errors, Map.of());
  }

  public static ApiProblem unprocessable(String slug, String title, String detail) {
    return of(HttpStatus.UNPROCESSABLE_ENTITY, slug, title, detail);
  }

  public static ApiProblem conflict(String slug, String title, String detail) {
    return of(HttpStatus.CONFLICT, slug, title, detail);
  }

  public static ApiProblem preconditionFailed(String detail) {
    return of(HttpStatus.PRECONDITION_FAILED, "precondition-failed", "Precondition failed", detail);
  }

  public static ApiProblem unavailable(String detail, int retryAfterSeconds) {
    return new ApiProblem(
        HttpStatus.SERVICE_UNAVAILABLE,
        "service-unavailable",
        "Service unavailable",
        detail,
        List.of(),
        Map.of("Retry-After", Integer.toString(retryAfterSeconds)));
  }

  public HttpStatus status() {
    return status;
  }

  public String type() {
    return TYPE_BASE + slug;
  }

  public String title() {
    return title;
  }

  public List<FieldError> errors() {
    return errors;
  }

  public Map<String, String> headers() {
    return headers;
  }
}
