#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
TIMEOUT_SECONDS="${E2E_STACK_TIMEOUT:-180}"

if command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
else
  echo "docker-compose or docker compose is required" >&2
  exit 1
fi

cd "$PROJECT_ROOT"

$COMPOSE -f "$COMPOSE_FILE" up -d

deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))
last_status=""

while [ "$(date +%s)" -lt "$deadline" ]; do
  ids=$($COMPOSE -f "$COMPOSE_FILE" ps -q)
  if [ -n "$ids" ]; then
    all_healthy=1
    last_status=""
    for id in $ids; do
      name=$(docker inspect --format '{{.Name}}' "$id" 2>/dev/null | sed 's#^/##')
      health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id" 2>/dev/null || echo unknown)
      last_status="$last_status $name=$health"
      if [ "$health" != "healthy" ]; then
        all_healthy=0
      fi
    done

    if [ "$all_healthy" -eq 1 ]; then
      echo "READY"
      exit 0
    fi
  fi

  sleep 2
done

echo "services did not become healthy before timeout:$last_status" >&2
$COMPOSE -f "$COMPOSE_FILE" logs --no-color >&2 || true
exit 1
