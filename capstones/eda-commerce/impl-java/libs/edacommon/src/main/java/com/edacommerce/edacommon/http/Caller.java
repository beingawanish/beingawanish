package com.edacommerce.edacommon.http;

import com.edacommerce.edacommon.config.EdaProperties;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;

/**
 * Who is calling: the JWT subject with AUTH_MODE=oidc. With AUTH_MODE=none (local only) the caller
 * is taken from the optional {@value #LOCAL_CUSTOMER_HEADER} header, else {@value #LOCAL_CUSTOMER}.
 */
public class Caller {
  public static final String LOCAL_CUSTOMER_HEADER = "X-Local-Customer-Id";
  public static final String LOCAL_CUSTOMER = "local-customer";

  private final EdaProperties properties;

  public Caller(EdaProperties properties) {
    this.properties = properties;
  }

  /** Customer id or client id of the current request. */
  public String id(HttpServletRequest request) {
    Authentication auth = SecurityContextHolder.getContext().getAuthentication();
    if (auth instanceof JwtAuthenticationToken jwt) {
      return jwt.getToken().getSubject();
    }
    if (properties.getAuth().getMode() == EdaProperties.AuthMode.NONE) {
      String header = request.getHeader(LOCAL_CUSTOMER_HEADER);
      return header == null || header.isBlank() ? LOCAL_CUSTOMER : header;
    }
    return "anonymous";
  }
}
