# ADR-0012: REST at the edge, with Idempotency-Key and 202 Accepted for asynchronous work

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** ADR-0006, contracts/openapi/*.yaml

## Context

Customers and the storefront talk to the system over HTTP. Networks drop responses. Mobile clients retry. A user double-clicks "Place order". Without protection, a retried POST creates a second order and a second charge. Meanwhile the real work behind "place order" takes seconds to minutes and must not hold an HTTP request open.

## Decision

- **REST + JSON**, described in OpenAPI 3.1 (`contracts/openapi/`). Errors are RFC 9457 problem details.
- **Every unsafe POST requires an `Idempotency-Key` header.** The server stores `(caller, key) → request hash, status, response` in the `idempotency_key` table for 24 hours:
  - first request: insert with `IN_PROGRESS` in the same transaction as the business change, then store the response as `COMPLETED`;
  - same key, same body, completed: replay the stored response with `Idempotent-Replayed: true`;
  - same key, same body, still in progress: `409` with `Retry-After`;
  - same key, different body: `422`.
- **Asynchronous operations answer `202 Accepted`** with the resource id and a `Location` to poll (`POST /checkouts` → `/orders/{orderId}`; `POST /returns` → `/returns/{returnId}`). The response is ready as soon as the outbox row commits.
- **PUT for idempotent-by-nature updates** (set cart item quantity), with `If-Match`/`ETag` for optimistic concurrency.
- **Reads** carry a `version` and an `ETag`; clients poll with `If-None-Match` and back off using `Retry-After`.
- **Money** is integer minor units plus currency, never floats. **`expectedTotal`** at checkout protects against price changes between view and submit.

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it |
|---|---|---|
| Synchronous checkout (wait for the saga) | Simple client | Request held for up to minutes (PSP timeout path); timeouts at proxies; retries create duplicates anyway |
| Server-side dedupe on body hash only | No client change | Two legitimate identical orders would be merged; no way to distinguish a retry from a repeat |
| GraphQL | Flexible reads | Mutations still need idempotency; less natural for 202 + polling; REST is enough here |
| gRPC at the edge | Typed, fast | Browser support needs a proxy; public APIs are usually REST |
| Push status via WebSocket/SSE | No polling | Extra infrastructure; polling with `Retry-After` is enough for a capstone; SSE can be added on top of the read model later |

## Consequences

- The idempotency middleware lives in the shared library and is identical in behaviour across languages (same table, same hash: SHA-256 over method, path and canonical JSON body).
- Clients must generate a key per user intent and reuse it on retries. The storefront generates it when the checkout page loads.
- Polling load lands on the read model, which is designed for it (ADR-0010).

## Trade-offs

We gain safe retries for every client, short requests, and an API that matches how the system actually works. We pay with a stored response per POST for 24 hours, a polling client, and the need to explain "accepted" versus "done" in the UI.

## When to revisit

- Clients need instant updates: add SSE on top of order-history changes.
- Internal machine clients multiply: consider gRPC internally, keep REST at the edge.
