#!/usr/bin/env bash
# Create or update the Debezium outbox connector of each service (PUT is idempotent).
# A connector can only start once its service has run its first migration, because the
# migration creates the outbox table and the outbox_pub publication (contracts/sql/common-tables.sql).
#
#   ./register-connectors.sh                 # all services
#   ./register-connectors.sh order payment   # some services
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CONNECT_URL="${CONNECT_URL:-http://localhost:8083}"
services=("$@")
if [[ ${#services[@]} -eq 0 ]]; then
  services=(catalog checkout order payment inventory fulfilment shipping notification returns)
fi
for svc in "${services[@]}"; do
  file="$HERE/../connect/connectors/${svc}-svc-outbox.json"
  name="${svc}-svc-outbox"
  config="$(jq '.config' "$file")"
  code=$(curl -s -o /tmp/connect-resp.$$ -w '%{http_code}' -X PUT -H 'Content-Type: application/json' \
         --data "$config" "$CONNECT_URL/connectors/$name/config")
  if [[ "$code" =~ ^20[01]$ ]]; then
    echo "connector $name: ok"
  else
    echo "connector $name: HTTP $code: $(cat /tmp/connect-resp.$$)" >&2
  fi
done
rm -f /tmp/connect-resp.$$
echo
curl -s "$CONNECT_URL/connectors?expand=status" | jq -r 'to_entries[] | "\(.key)\t\(.value.status.connector.state)\t\(.value.status.tasks | map(.state) | join(","))"'
