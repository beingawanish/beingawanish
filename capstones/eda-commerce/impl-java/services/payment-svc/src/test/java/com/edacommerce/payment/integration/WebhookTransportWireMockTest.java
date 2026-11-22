package com.edacommerce.payment.integration;

import static com.github.tomakehurst.wiremock.client.WireMock.aResponse;
import static com.github.tomakehurst.wiremock.client.WireMock.equalTo;
import static com.github.tomakehurst.wiremock.client.WireMock.post;
import static com.github.tomakehurst.wiremock.client.WireMock.postRequestedFor;
import static com.github.tomakehurst.wiremock.client.WireMock.urlEqualTo;
import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.webhooks.WebhookVerifier;
import com.edacommerce.payment.adapters.out.psp.fake.HttpPspWebhookTransport;
import com.github.tomakehurst.wiremock.WireMockServer;
import com.github.tomakehurst.wiremock.core.WireMockConfiguration;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import org.junit.jupiter.api.Test;

/** The fake PSP's webhook client sends what a real PSP sends, and retries 5xx until a 2xx. */
class WebhookTransportWireMockTest {
  @Test
  void postsSignedWebhooksAndRetriesServerErrors() {
    WireMockServer server = new WireMockServer(WireMockConfiguration.options().dynamicPort());
    server.start();
    try {
      server.stubFor(post("/webhooks/psp").inScenario("s").whenScenarioStateIs("Started").willReturn(aResponse().withStatus(503)).willSetStateTo("up"));
      server.stubFor(post("/webhooks/psp").inScenario("s").whenScenarioStateIs("up").willReturn(aResponse().withStatus(200)));
      WebhookVerifier signer = new WebhookVerifier("dev-psp-secret", Clock.systemUTC());
      byte[] body = "{\"pspEventId\":\"e1\"}".getBytes(StandardCharsets.UTF_8);
      long ts = System.currentTimeMillis() / 1000;
      new HttpPspWebhookTransport("http://localhost:" + server.port() + "/webhooks/psp", 3).send(body, ts, signer.sign(ts, body));

      server.verify(2, postRequestedFor(urlEqualTo("/webhooks/psp"))
          .withHeader("X-Webhook-Timestamp", equalTo(Long.toString(ts)))
          .withHeader("X-Psp-Signature", equalTo(signer.sign(ts, body))));
      var req = server.getAllServeEvents().get(0).getRequest();
      assertThat(signer.rejectionReason(req.getHeader("X-Webhook-Timestamp"), req.getHeader("X-Psp-Signature"), req.getBody())).isNull();
    } finally {
      server.stop();
    }
  }
}
