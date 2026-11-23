#!/usr/bin/env bash
# Chaos drills (docs/architecture.md section "Chaos drills"). Each drill states what it breaks;
# the expected outcome and the signal to watch are in the architecture document.
#
#   ./chaos.sh <drill> [args]
#
# Infrastructure drills act on containers. Fake drills call the admin APIs of payment-svc,
# fulfilment-svc and shipping-svc (contracts/openapi/admin.yaml), so they behave the same
# against the Python and the Java builds.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMPOSE="${COMPOSE:-docker compose -f $HERE/../docker-compose.yml}"
PAYMENT_URL="${PAYMENT_URL:-http://localhost:8104}"
FULFILMENT_URL="${FULFILMENT_URL:-http://localhost:8106}"
SHIPPING_URL="${SHIPPING_URL:-http://localhost:8107}"
DURATION="${DURATION:-30}"

put() { curl -fsS -X PUT -H 'Content-Type: application/json' --data "$2" "$1" > /dev/null && echo "applied $2 -> $1"; }

case "${1:-help}" in
  kafka-pause)        # Broker unreachable. Producers (Connect) and consumers stall; nothing is lost.
    $COMPOSE pause kafka; echo "kafka paused for ${DURATION}s"; sleep "$DURATION"; $COMPOSE unpause kafka ;;
  connect-kill)       # Relay down. Business writes keep succeeding; outbox rows pile up; events arrive late, in order.
    $COMPOSE kill connect; echo "connect killed for ${DURATION}s"; sleep "$DURATION"; $COMPOSE start connect ;;
  postgres-pause)     # Every service's database stalls. HTTP returns 503 fast; consumers stop committing and retry in place.
    $COMPOSE pause postgres; echo "postgres paused for ${DURATION}s"; sleep "$DURATION"; $COMPOSE unpause postgres ;;
  minio-stop)         # Claim-check store down. Producers of large payloads fail before writing the outbox row; consumers retry downloads.
    $COMPOSE stop minio; echo "minio stopped for ${DURATION}s"; sleep "$DURATION"; $COMPOSE start minio ;;
  schema-registry-stop) # Cached schema ids keep working; new producers or new schemas fail loudly.
    $COMPOSE stop schema-registry; echo "schema registry stopped for ${DURATION}s"; sleep "$DURATION"; $COMPOSE start schema-registry ;;
  service-kill)       # SIGKILL one service process mid-flight. Needs SVC=<process pattern>, e.g. SVC=order-svc.
    : "${SVC:?set SVC, e.g. SVC=order-svc}"
    pkill -9 -f "$SVC" && echo "killed $SVC; restart it and watch the saga resume" ;;
  psp-declines)       # Half of all authorisations decline.
    put "$PAYMENT_URL/admin/fakes/psp" '{"declineRate":0.5}' ;;
  psp-timeouts)       # A third of PSP calls hang; reconciliation must resolve them.
    put "$PAYMENT_URL/admin/fakes/psp" '{"timeoutRate":0.33}' ;;
  psp-duplicates)     # Every webhook is delivered several times.
    put "$PAYMENT_URL/admin/fakes/psp" '{"duplicateWebhookRate":1.0}' ;;
  wms-lossy)          # The warehouse loses 50% of fulfilment requests and is very slow.
    put "$FULFILMENT_URL/admin/fakes/wms" '{"dropRequestRate":0.5,"acceptDelayMs":20000}' ;;
  carrier-chaos)      # Duplicated and reordered carrier webhooks.
    put "$SHIPPING_URL/admin/fakes/carrier" '{"duplicateRate":0.5,"outOfOrderRate":0.5}' ;;
  reset)              # Back to the default fake behaviour.
    put "$PAYMENT_URL/admin/fakes/psp" '{"declineRate":0.05,"timeoutRate":0.02,"duplicateWebhookRate":0.1}'
    put "$FULFILMENT_URL/admin/fakes/wms" '{"dropRequestRate":0.1,"acceptDelayMs":2000}'
    put "$SHIPPING_URL/admin/fakes/carrier" '{"duplicateRate":0.2,"outOfOrderRate":0.2}' ;;
  *)
    sed -n '2,9p' "$0"; echo; grep -E '^  [a-z-]+\)' "$0" | sed 's/)[^#]*#/ -/' ;;
esac
