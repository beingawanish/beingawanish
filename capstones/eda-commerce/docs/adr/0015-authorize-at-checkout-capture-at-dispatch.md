# ADR-0015: Authorise at checkout, capture at dispatch; dispatch is the saga's pivot

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** ADR-0001, ADR-0008, docs/architecture.md §5

## Context

When do we take the customer's money? Card scheme rules and consumer law in many markets say a merchant should not capture funds before the goods ship. Capturing early also makes every later failure (warehouse cannot find the item) a refund, which costs fees and customer trust. Capturing late risks the authorisation expiring (typically about 7 days) before dispatch.

In saga terms, some step must be the **pivot**: the point after which the flow can only go forward. Before it, everything is compensatable. After it, everything must be retried until it succeeds or a human steps in.

## Decision

- **Authorise** during the order saga, right after stock is reserved. An authorisation holds funds but moves no money. Its compensation is a cheap **void**.
- **Capture** when fulfilment reports **`OrderDispatched`** (the carrier scanned the parcel out of the warehouse).
- **Dispatch is the pivot.** Before it: reservation, authorisation and fulfilment request are compensated on failure (release, void, cancel fulfilment). After it: capture is retried with backoff; if it fails permanently (for example `AUTHORIZATION_EXPIRED`), the saga moves to `NEEDS_ATTENTION` and emits `OrderRequiresAttention`. Code never tries to "un-ship".
- The customer-facing status separates **CONFIRMED** (we will ship) from **SHIPPED** (shipped and paid). Nobody calls an order "paid" before capture.
- The saga stores `authorizationExpiresAt`. If dispatch has not happened two days before it, the saga raises `OrderRequiresAttention` so ops can re-authorise before it lapses.

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it |
|---|---|---|
| Capture at checkout (sale) | Simplest; money in hand | Against scheme rules in many markets; every fulfilment failure becomes a refund with fees; customer sees a charge for something that may never ship |
| Capture at delivery | Most customer-friendly | Authorisations expire long before slow deliveries; carrier delays turn into payment failures |
| Pivot at packing | Earlier certainty | A packed parcel can still be unpacked and cancelled; dispatch is the real point of no return |

## Consequences

- Payment has two money-moving commands with different failure handling, and the saga has an explicit "past the pivot" region.
- There is a real business risk: goods shipped, capture failed. It is rare, visible (alert, dashboard), and owned by a human. That is the honest design.
- Refunds (returns saga) are only possible after capture, so return eligibility requires `OrderShipped`.

## Trade-offs

We gain compliance with common scheme rules, cheap cancellations before shipping, and a clear compensation boundary. We pay with authorisation-expiry handling and a small, explicit class of orders that need manual follow-up.

## When to revisit

- Digital goods or services with no physical dispatch: capture at fulfilment of the service.
- Markets or payment methods without authorisation (some bank transfers, wallets): the pivot becomes payment itself, and stock is committed only after money arrives.
- Split shipments: capture per shipment (partial captures), one pivot per parcel.
