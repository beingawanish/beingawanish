package com.edacommerce.edacommon.http;

import com.edacommerce.edacommon.config.EdaProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2Error;
import org.springframework.security.oauth2.core.OAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtDecoders;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.web.SecurityFilterChain;

/**
 * Edge security (ADR-0013). AUTH_MODE=oidc validates bearer JWTs (signature, issuer, audience,
 * expiry) and authorises on scopes: {@code ops} for /admin and /ops, {@code shop} elsewhere.
 * AUTH_MODE=none permits everything and is refused unless ENVIRONMENT=local. Health and webhooks
 * (HMAC-signed) are always open; product browsing is public.
 */
@Configuration(proxyBeanMethods = false)
public class SecurityConfiguration {

  @Bean
  SecurityFilterChain edaSecurity(HttpSecurity http, EdaProperties properties) throws Exception {
    http.csrf(c -> c.disable())
        .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
        .httpBasic(b -> b.disable())
        .formLogin(f -> f.disable());
    if (properties.getAuth().getMode() == EdaProperties.AuthMode.NONE) {
      if (!properties.isLocal()) {
        throw new IllegalStateException(
            "AUTH_MODE=none is only allowed with ENVIRONMENT=local (current: " + properties.getEnvironment() + ")");
      }
      http.authorizeHttpRequests(a -> a.anyRequest().permitAll());
      return http.build();
    }
    JwtDecoder decoder = jwtDecoder(properties);
    http.authorizeHttpRequests(
            a ->
                a.requestMatchers("/health/**", "/webhooks/**", "/actuator/health/**")
                    .permitAll()
                    .requestMatchers(HttpMethod.GET, "/products", "/products/**")
                    .permitAll()
                    .requestMatchers("/admin/**", "/ops/**")
                    .hasAuthority("SCOPE_ops")
                    .anyRequest()
                    .hasAuthority("SCOPE_shop"))
        .oauth2ResourceServer(o -> o.jwt(j -> j.decoder(decoder)));
    return http.build();
  }

  static JwtDecoder jwtDecoder(EdaProperties properties) {
    String issuer = properties.getAuth().getIssuerUrl();
    NimbusJwtDecoder decoder = (NimbusJwtDecoder) JwtDecoders.fromIssuerLocation(issuer);
    String audience = properties.getAuth().getAudience();
    OAuth2TokenValidator<Jwt> audienceValidator =
        jwt ->
            jwt.getAudience() != null && jwt.getAudience().contains(audience)
                ? OAuth2TokenValidatorResult.success()
                : OAuth2TokenValidatorResult.failure(
                    new OAuth2Error("invalid_token", "audience must contain " + audience, null));
    decoder.setJwtValidator(
        new DelegatingOAuth2TokenValidator<>(JwtValidators.createDefaultWithIssuer(issuer), audienceValidator));
    return decoder;
  }
}
