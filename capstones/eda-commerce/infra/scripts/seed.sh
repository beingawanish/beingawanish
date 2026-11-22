#!/usr/bin/env bash
# Seed products, prices and stock through the services' own admin APIs (contracts/openapi/catalog.yaml
# and admin.yaml). Going through the API, not SQL, means the seed also exercises the outbox:
# after it runs, catalog.product.v1, catalog.price.v1 and inventory.stock-level.v1 must contain
# one record per SKU. Needs catalog-svc (8101) and inventory-svc (8105) running.
#
# The SKUs are chosen for the drills: SKU-1005 has 1 unit (two buyers race), SKU-1006 has 0
# (OUT_OF_STOCK cancellation), SKU-1007 is discontinued (checkout must refuse it).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CATALOG_URL="${CATALOG_URL:-http://localhost:8101}"
INVENTORY_URL="${INVENTORY_URL:-http://localhost:8105}"
TOKEN_HEADER=()
[[ -n "${OPS_TOKEN:-}" ]] && TOKEN_HEADER=(-H "Authorization: Bearer $OPS_TOKEN")

jq -c '.[]' "$HERE/../seed/products.json" | while read -r p; do
  sku=$(jq -r .sku <<<"$p")
  body=$(jq 'del(.sku, .onHand)' <<<"$p")
  onhand=$(jq -r .onHand <<<"$p")
  curl -fsS -X PUT "${TOKEN_HEADER[@]}" -H 'Content-Type: application/json' \
       --data "$body" "$CATALOG_URL/admin/products/$sku" > /dev/null
  curl -fsS -X PUT "${TOKEN_HEADER[@]}" -H 'Content-Type: application/json' \
       --data "{\"onHand\": $onhand}" "$INVENTORY_URL/admin/stock/$sku" > /dev/null
  echo "seeded $sku (onHand=$onhand)"
done
