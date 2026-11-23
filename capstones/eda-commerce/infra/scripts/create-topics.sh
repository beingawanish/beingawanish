#!/usr/bin/env bash
# Create every topic in infra/topics.conf (generated from contracts/topics.yaml).
# Idempotent: existing topics are left alone, but a partition-count mismatch is reported,
# because it means the catalogue and the cluster disagree about key -> partition mapping.
#
#   RF=1 ./create-topics.sh                 # local single broker (default)
#   RF=3 BOOTSTRAP=broker:9092 KAFKA_CMD=kafka-topics ./create-topics.sh   # against a real cluster
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CONF="${CONF:-$HERE/../topics.conf}"
RF="${RF:-1}"
BOOTSTRAP="${BOOTSTRAP:-kafka:29092}"
COMPOSE="${COMPOSE:-docker compose -f $HERE/../docker-compose.yml}"
# By default run kafka-topics inside the broker container, so the host needs no Kafka tools.
KAFKA_CMD="${KAFKA_CMD:-$COMPOSE exec -T kafka kafka-topics}"
MIN_ISR=$(( RF >= 3 ? 2 : 1 ))

existing="$($KAFKA_CMD --bootstrap-server "$BOOTSTRAP" --list)"
created=0; skipped=0; mismatched=0

while read -r name partitions cleanup retention; do
  [[ -z "${name:-}" || "${name:0:1}" == "#" ]] && continue
  if grep -qx "$name" <<<"$existing"; then
    actual="$($KAFKA_CMD --bootstrap-server "$BOOTSTRAP" --describe --topic "$name" | sed -n 's/.*PartitionCount: *\([0-9]*\).*/\1/p' | head -1)"
    if [[ "$actual" != "$partitions" ]]; then
      echo "MISMATCH $name has $actual partitions, catalogue says $partitions" >&2
      mismatched=$((mismatched + 1))
    fi
    skipped=$((skipped + 1))
    continue
  fi
  extra=()
  if [[ "$cleanup" == "compact" ]]; then
    # Keep at least a minute of history uncompacted so slow consumers still see recent changes.
    extra+=(--config min.compaction.lag.ms=60000 --config segment.ms=3600000 --config delete.retention.ms=86400000)
  fi
  $KAFKA_CMD --bootstrap-server "$BOOTSTRAP" --create --if-not-exists \
    --topic "$name" --partitions "$partitions" --replication-factor "$RF" \
    --config cleanup.policy="$cleanup" --config retention.ms="$retention" \
    --config min.insync.replicas="$MIN_ISR" --config compression.type=producer \
    "${extra[@]}" > /dev/null
  echo "created $name (p=$partitions, $cleanup, retention.ms=$retention)"
  created=$((created + 1))
done < "$CONF"

echo "topics: $created created, $skipped already present, $mismatched mismatched"
[[ $mismatched -eq 0 ]]
