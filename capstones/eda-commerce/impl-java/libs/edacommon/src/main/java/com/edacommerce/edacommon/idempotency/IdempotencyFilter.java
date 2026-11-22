package com.edacommerce.edacommon.idempotency;

import com.edacommerce.edacommon.http.ApiProblem;
import com.edacommerce.edacommon.http.Caller;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ReadListener;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletInputStream;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import java.io.BufferedReader;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.http.MediaType;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.util.AntPathMatcher;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.util.ContentCachingResponseWrapper;

/**
 * {@code Idempotency-Key} handling for unsafe POSTs (ADR-0012), identical in behaviour to the
 * Python build: same table, same hash.
 *
 * <p>The whole request runs in one database transaction that also holds a transaction-scoped
 * advisory lock on (caller, key) and the key row itself. That gives the four contract outcomes:
 *
 * <ul>
 *   <li>first request: row inserted IN_PROGRESS, the controller's business change and outbox rows
 *       join this transaction, the 2xx response is stored COMPLETED, all commit together;
 *   <li>same key and body, completed: the stored response is replayed with {@code
 *       Idempotent-Replayed: true};
 *   <li>same key while the first is still running: the advisory lock is taken, so 409 with
 *       Retry-After, immediately;
 *   <li>same key, different body: 422.
 * </ul>
 *
 * A non-2xx response rolls everything back and stores nothing, so the client may retry. Because the
 * key row and the business change share one transaction, a crash can never leave a key that
 * "completed" without its effect, or an effect without its key.
 */
public class IdempotencyFilter extends OncePerRequestFilter {
  public static final String HEADER = "Idempotency-Key";
  public static final String REPLAYED = "Idempotent-Replayed";
  static final List<String> STORED_HEADERS =
      List.of("Location", "ETag", "Retry-After", "Content-Type");

  private final IdempotencyStore store;
  private final TransactionTemplate tx;
  private final Caller caller;
  private final List<String> paths;
  private final Duration ttl;
  private final Clock clock;
  private final AntPathMatcher matcher = new AntPathMatcher();
  private final com.fasterxml.jackson.databind.ObjectMapper json =
      new com.fasterxml.jackson.databind.ObjectMapper();

  public IdempotencyFilter(
      IdempotencyStore store,
      TransactionTemplate tx,
      Caller caller,
      List<String> paths,
      Duration ttl,
      Clock clock) {
    this.store = store;
    this.tx = tx;
    this.caller = caller;
    this.paths = List.copyOf(paths);
    this.ttl = ttl;
    this.clock = clock;
  }

  @Override
  protected boolean shouldNotFilter(HttpServletRequest request) {
    if (!"POST".equalsIgnoreCase(request.getMethod())) {
      return true;
    }
    String path = request.getRequestURI();
    return paths.stream().noneMatch(p -> matcher.match(p, path));
  }

  @Override
  protected void doFilterInternal(
      HttpServletRequest request, HttpServletResponse response, FilterChain chain)
      throws ServletException, IOException {
    String key = request.getHeader(HEADER);
    if (key == null || key.isBlank() || key.length() > 255) {
      writeProblem(
          response,
          ApiProblem.badRequest(
              "idempotency-key-required",
              "An Idempotency-Key header (1-255 characters) is required",
              List.of(new ApiProblem.FieldError(HEADER, "required, at most 255 characters"))));
      return;
    }
    byte[] body = request.getInputStream().readAllBytes();
    String path = request.getRequestURI();
    String hash = CanonicalJson.requestHash(request.getMethod(), path, body);
    String who = caller.id(request);
    CachedBodyRequest wrapped = new CachedBodyRequest(request, body);
    ContentCachingResponseWrapper captured = new ContentCachingResponseWrapper(response);

    Outcome outcome =
        tx.execute(
            status -> {
              Instant now = clock.instant();
              if (!store.tryLock(who, key)) {
                return Outcome.IN_PROGRESS;
              }
              Optional<IdempotencyStore.StoredKey> existing = store.find(who, key, now);
              if (existing.isPresent()) {
                IdempotencyStore.StoredKey stored = existing.get();
                if (!stored.requestHash().equals(hash)) {
                  return Outcome.MISMATCH;
                }
                if (!stored.completed()) {
                  return Outcome.IN_PROGRESS;
                }
                return Outcome.replay(stored);
              }
              store.begin(who, key, hash, now, now.plus(ttl));
              try {
                chain.doFilter(wrapped, captured);
              } catch (IOException e) {
                throw new UncheckedIOException(e);
              } catch (ServletException e) {
                throw new IllegalStateException(e);
              }
              int code = captured.getStatus();
              if (code >= 200 && code < 300) {
                store.complete(
                    who, key, code, headersOf(captured), captured.getContentAsByteArray());
              } else {
                status.setRollbackOnly();
              }
              return Outcome.EXECUTED;
            });

    switch (outcome.kind) {
      case EXECUTED -> captured.copyBodyToResponse();
      case IN_PROGRESS -> {
        response.setHeader("Retry-After", "1");
        writeProblem(
            response,
            ApiProblem.conflict(
                "idempotency-in-progress",
                "Request in progress",
                "A request with this Idempotency-Key is still being processed"));
      }
      case MISMATCH ->
          writeProblem(
              response,
              ApiProblem.unprocessable(
                  "idempotency-key-reused",
                  "Idempotency-Key reused",
                  "This Idempotency-Key was already used with a different request body"));
      case REPLAY -> {
        IdempotencyStore.StoredKey stored = outcome.stored;
        response.setStatus(stored.responseStatus() == null ? 200 : stored.responseStatus());
        stored.responseHeaders().forEach(response::setHeader);
        response.setHeader(REPLAYED, "true");
        if (stored.responseBody() != null) {
          response.getOutputStream().write(stored.responseBody());
        }
      }
    }
  }

  private static Map<String, String> headersOf(HttpServletResponse response) {
    Map<String, String> headers = new LinkedHashMap<>();
    for (String name : STORED_HEADERS) {
      String value = response.getHeader(name);
      if (value != null) {
        headers.put(name, value);
      }
    }
    if (!headers.containsKey("Content-Type") && response.getContentType() != null) {
      headers.put("Content-Type", response.getContentType());
    }
    return headers;
  }

  private void writeProblem(HttpServletResponse response, ApiProblem problem) throws IOException {
    response.setStatus(problem.status().value());
    response.setContentType(MediaType.APPLICATION_PROBLEM_JSON_VALUE);
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("type", problem.type());
    body.put("title", problem.title());
    body.put("status", problem.status().value());
    body.put("detail", problem.getMessage());
    if (!problem.errors().isEmpty()) {
      body.put("errors", problem.errors());
    }
    response.getOutputStream().write(json.writeValueAsBytes(body));
  }

  private static final class Outcome {
    enum Kind {
      EXECUTED,
      IN_PROGRESS,
      MISMATCH,
      REPLAY
    }

    static final Outcome EXECUTED = new Outcome(Kind.EXECUTED, null);
    static final Outcome IN_PROGRESS = new Outcome(Kind.IN_PROGRESS, null);
    static final Outcome MISMATCH = new Outcome(Kind.MISMATCH, null);

    final Kind kind;
    final IdempotencyStore.StoredKey stored;

    private Outcome(Kind kind, IdempotencyStore.StoredKey stored) {
      this.kind = kind;
      this.stored = stored;
    }

    static Outcome replay(IdempotencyStore.StoredKey stored) {
      return new Outcome(Kind.REPLAY, stored);
    }
  }

  /** Lets the controller read the body the filter already consumed. */
  static final class CachedBodyRequest extends HttpServletRequestWrapper {
    private final byte[] body;

    CachedBodyRequest(HttpServletRequest request, byte[] body) {
      super(request);
      this.body = body;
    }

    @Override
    public ServletInputStream getInputStream() {
      ByteArrayInputStream in = new ByteArrayInputStream(body);
      return new ServletInputStream() {
        @Override
        public boolean isFinished() {
          return in.available() == 0;
        }

        @Override
        public boolean isReady() {
          return true;
        }

        @Override
        public void setReadListener(ReadListener listener) {
          throw new UnsupportedOperationException();
        }

        @Override
        public int read() {
          return in.read();
        }

        @Override
        public int read(byte[] b, int off, int len) {
          return in.read(b, off, len);
        }
      };
    }

    @Override
    public BufferedReader getReader() {
      return new BufferedReader(new InputStreamReader(getInputStream(), StandardCharsets.UTF_8));
    }

    @Override
    public int getContentLength() {
      return body.length;
    }

    @Override
    public long getContentLengthLong() {
      return body.length;
    }
  }
}
