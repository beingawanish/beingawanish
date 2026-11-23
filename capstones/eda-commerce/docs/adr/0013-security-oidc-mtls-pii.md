# ADR-0013: Security baseline: OIDC at the edge, mTLS inside, minimal personal data in events

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** ADR-0004, ADR-0009, ADR-0011, contracts/openapi/common.yaml, contracts/openapi/webhooks.yaml

## Context

A shop handles credentials, addresses, emails and payments. Events are copied into many consumers and retained for weeks, and Kafka has no "delete this customer" button. Regulations (GDPR and similar) give customers the right to erasure. Card data must never enter our systems at all (PCI DSS scope).

This is a capstone, so the goal is a **correct baseline** that a real deployment hardens, not a full security programme.

## Decision

**Identity at the edge.**

- Customers and staff authenticate with an **OIDC** provider (Keycloak locally, `make up-all`). Public APIs require a bearer JWT. Services validate signature, issuer, audience and expiry against the provider's JWKS and authorise on scopes (`shop`, `ops`) and on ownership (a customer can read only their own orders).
- `AUTH_MODE=none` exists for local development only. Services refuse to start with `AUTH_MODE=none` unless `ENVIRONMENT=local`.

**Service to service.**

- In Kubernetes, a service mesh (or cert-manager issued certificates) provides **mTLS** for HTTP between services. There is little such traffic: services integrate over Kafka.
- Kafka uses **mTLS client authentication** (`SSL`) with one certificate per service (CN = service name). **ACLs** follow the catalogue: a service may write only its own event topic and the command topics it is a declared producer of (from `topics.yaml`), and read only the topics it is a declared consumer of, plus its own retry and DLQ topics. ACLs can be generated from the catalogue.
- Schema Registry: read for all services, write only for the CI identity (ADR-0004).
- Object storage: per-service identity; producer writes its bucket; named consumers read.

**Webhooks.** HMAC-SHA256 signature over `"<timestamp>.<raw body>"`, 5-minute timestamp tolerance, constant-time comparison, inbox dedupe on provider event id (`contracts/openapi/webhooks.yaml`).

**Payment data.** Only PSP tokens (`paymentMethodToken`) enter the system. No card numbers, ever, in any field, log or event.

**Personal data in events.**

- Default: events carry **ids, not people**. `customerId` yes; name, email, address no.
- Exceptions are explicit and tagged `"pii": true` in the schema: `CheckoutSubmitted` and `OrderPlaced` (address, email), `RequestFulfilment` and `OrderPacked` (ship-to address), `IssueReturnLabel` (pickup address). Those consumers need the data to do their job.
- Topics that carry PII have **bounded retention** (7–90 days) and restricted ACLs.
- notification-svc and the services that keep addresses own erasure for their copies. An erasure request is an event (`CustomerErased`, not yet in the contracts; see "When to revisit") that each holder handles.
- Logs and traces must never contain PII. The shared logging library redacts fields tagged PII; the collector deletes common PII attributes as a second line of defence.

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it (yet) |
|---|---|---|
| Crypto-shredding (encrypt PII fields per customer, delete the key to erase) | True erasure even inside retained events and backups | Key management service, per-field encryption in both languages, harder debugging; worth it when retention grows beyond 90 days |
| No PII in any event; consumers call a customer service | Smallest exposure | Synchronous dependency on a customer service for fulfilment and shipping; that service does not exist in this domain |
| API keys between services | Simple | Long-lived shared secrets; no identity per instance; mTLS is the standard in a mesh |
| SASL/SCRAM for Kafka | Simple username/password | Fine too; mTLS lines up with mesh identities and avoids password rotation |

## Consequences

- Each service has a certificate, an ACL set and a bucket policy. Generating them from `topics.yaml` keeps them in sync with the catalogue.
- Reviews check the `pii` tag on every new field that could identify a person.
- The local stack runs PLAINTEXT and without auth by default for speed; the `auth` profile exercises the real token flow.

## Trade-offs

We gain least privilege on the broker and storage, a clean PCI boundary, and a visible, reviewable list of where personal data flows. We pay with certificate management, ACL generation and some friction locally. We accept that PII inside retained events is erased only by retention expiry, not instantly.

## When to revisit

- Any PII-carrying topic needs retention longer than 90 days, or backups of Kafka are kept: adopt crypto-shredding for the tagged fields.
- A customer service context is introduced: replace inline addresses with references where latency allows.
- An erasure request flow is required by the business: add `CustomerErased` to the contracts and an erasure checklist per service.
