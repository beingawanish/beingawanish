package com.edacommerce.edacommon.testing;

import com.atlassian.oai.validator.OpenApiInteractionValidator;
import com.atlassian.oai.validator.mockmvc.OpenApiValidationMatchers;
import com.atlassian.oai.validator.report.LevelResolver;
import com.atlassian.oai.validator.report.ValidationReport;
import org.springframework.test.web.servlet.ResultMatcher;

/**
 * Validates MockMvc responses against a contracts/openapi document (checklist "HTTP responses
 * validate against the OpenAPI document"). Request validation is relaxed (tests send deliberately
 * bad requests); responses are validated strictly. Security is not validated (AUTH_MODE=none tests).
 */
public final class OpenApiContract {
  private OpenApiContract() {}

  public static ResultMatcher validResponse(String document) {
    OpenApiInteractionValidator validator =
        OpenApiInteractionValidator.createForSpecificationUrl(Contracts.openApi(document).toUri().toString())
            .withResolveCombinators(true)
            .withLevelResolver(
                LevelResolver.create()
                    .withLevel("validation.request", ValidationReport.Level.IGNORE)
                    .withLevel("validation.response.security", ValidationReport.Level.IGNORE)
                    .withLevel("validation.request.security", ValidationReport.Level.IGNORE)
                    // The contracts do not forbid extra properties; do not inject additionalProperties=false.
                    .withLevel("validation.schema.additionalProperties", ValidationReport.Level.IGNORE)
                    .withLevel("validation.response.body.schema.additionalProperties", ValidationReport.Level.IGNORE)
                    .build())
            .build();
    return OpenApiValidationMatchers.openApi().isValid(validator);
  }
}
