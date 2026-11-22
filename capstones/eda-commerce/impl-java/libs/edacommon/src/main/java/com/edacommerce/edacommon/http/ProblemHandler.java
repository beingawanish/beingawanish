package com.edacommerce.edacommon.http;

import com.edacommerce.edacommon.errors.ErrorClass;
import com.edacommerce.edacommon.errors.ErrorClassifier;
import io.opentelemetry.api.trace.Span;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.ConstraintViolationException;
import java.net.URI;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/**
 * Maps exceptions to RFC 9457 problem details (guide §6.3): 4xx for client problems, 503 with
 * Retry-After when a dependency is down, 500 only for the unknown.
 */
@RestControllerAdvice
public class ProblemHandler {
  private static final Logger log = LoggerFactory.getLogger(ProblemHandler.class);
  static final MediaType PROBLEM_JSON = MediaType.APPLICATION_PROBLEM_JSON;

  @ExceptionHandler(ApiProblem.class)
  public ResponseEntity<ProblemDetail> api(ApiProblem e, HttpServletRequest request) {
    ProblemDetail pd = ProblemDetail.forStatusAndDetail(e.status(), e.getMessage());
    pd.setType(URI.create(e.type()));
    pd.setTitle(e.title());
    if (!e.errors().isEmpty()) {
      pd.setProperty("errors", e.errors());
    }
    HttpHeaders headers = new HttpHeaders();
    e.headers().forEach(headers::add);
    return respond(pd, request, headers);
  }

  @ExceptionHandler(MethodArgumentNotValidException.class)
  public ResponseEntity<ProblemDetail> invalid(MethodArgumentNotValidException e, HttpServletRequest request) {
    List<ApiProblem.FieldError> errors =
        e.getBindingResult().getFieldErrors().stream()
            .map(f -> new ApiProblem.FieldError(f.getField(), String.valueOf(f.getDefaultMessage())))
            .toList();
    return api(ApiProblem.badRequest("validation", "The request failed validation", errors), request);
  }

  @ExceptionHandler(ConstraintViolationException.class)
  public ResponseEntity<ProblemDetail> constraint(ConstraintViolationException e, HttpServletRequest request) {
    List<ApiProblem.FieldError> errors =
        e.getConstraintViolations().stream()
            .map(v -> new ApiProblem.FieldError(v.getPropertyPath().toString(), v.getMessage()))
            .toList();
    return api(ApiProblem.badRequest("validation", "The request failed validation", errors), request);
  }

  @ExceptionHandler({
    HttpMessageNotReadableException.class,
    MissingRequestHeaderException.class,
    MethodArgumentTypeMismatchException.class
  })
  public ResponseEntity<ProblemDetail> malformed(Exception e, HttpServletRequest request) {
    return api(ApiProblem.badRequest("malformed-request", "The request is malformed", List.of()), request);
  }

  @ExceptionHandler(NoResourceFoundException.class)
  public ResponseEntity<ProblemDetail> noResource(NoResourceFoundException e, HttpServletRequest request) {
    return api(ApiProblem.notFound(request.getRequestURI()), request);
  }

  @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
  public ResponseEntity<ProblemDetail> method(HttpRequestMethodNotSupportedException e, HttpServletRequest request) {
    return api(
        ApiProblem.of(HttpStatus.METHOD_NOT_ALLOWED, "method-not-allowed", "Method not allowed", e.getMessage()),
        request);
  }

  @ExceptionHandler(Exception.class)
  public ResponseEntity<ProblemDetail> unknown(Exception e, HttpServletRequest request) {
    if (ErrorClassifier.classify(e) == ErrorClass.TRANSIENT) {
      log.warn("dependency unavailable while serving {}", request.getRequestURI(), e);
      return api(ApiProblem.unavailable("A dependency is temporarily unavailable", 5), request);
    }
    log.error("unexpected error serving {}", request.getRequestURI(), e);
    ProblemDetail pd = ProblemDetail.forStatusAndDetail(HttpStatus.INTERNAL_SERVER_ERROR, "Unexpected error");
    pd.setType(URI.create(ApiProblem.TYPE_BASE + "internal"));
    pd.setTitle("Internal error");
    return respond(pd, request, new HttpHeaders());
  }

  private static ResponseEntity<ProblemDetail> respond(
      ProblemDetail pd, HttpServletRequest request, HttpHeaders headers) {
    pd.setInstance(URI.create(request.getRequestURI()));
    String traceId = Span.current().getSpanContext().getTraceId();
    if (Span.current().getSpanContext().isValid()) {
      pd.setProperty("traceId", traceId);
    }
    return ResponseEntity.status(pd.getStatus()).headers(headers).contentType(PROBLEM_JSON).body(pd);
  }
}
