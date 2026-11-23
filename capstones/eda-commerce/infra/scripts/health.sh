#!/usr/bin/env bash
# One-line health per infrastructure component, from the host.
set -uo pipefail
check() { if eval "$2" > /dev/null 2>&1; then printf '  %-16s up\n' "$1"; else printf '  %-16s DOWN\n' "$1"; fi; }
echo "infrastructure:"
check kafka           "docker compose -f $(dirname "$0")/../docker-compose.yml exec -T kafka kafka-broker-api-versions --bootstrap-server localhost:9092"
check schema-registry "curl -fsS localhost:8081/subjects"
check connect         "curl -fsS localhost:8083/connectors"
check postgres        "docker compose -f $(dirname "$0")/../docker-compose.yml exec -T postgres pg_isready -U postgres"
check minio           "curl -fsS localhost:9000/minio/health/live"
check otel-collector  "curl -fsS localhost:13133"
check jaeger          "curl -fsS localhost:16686"
check prometheus      "curl -fsS localhost:9090/-/ready"
check grafana         "curl -fsS localhost:3000/api/health"
check kafka-ui        "curl -fsS localhost:8080/actuator/health"
echo "services:"
for p in 8101:catalog 8102:checkout 8103:order 8104:payment 8105:inventory 8106:fulfilment 8107:shipping 8108:notification 8109:returns; do
  check "${p#*:}-svc" "curl -fsS localhost:${p%%:*}/health/ready"
done
