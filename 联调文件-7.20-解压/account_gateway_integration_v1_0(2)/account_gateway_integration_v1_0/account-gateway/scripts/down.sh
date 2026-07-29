#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"

if command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
else
  echo "docker-compose or docker compose is required" >&2
  exit 1
fi

cd "$PROJECT_ROOT"

first_container=$($COMPOSE -f "$COMPOSE_FILE" ps -q | sed -n '1p')
project_name=""
if [ -n "$first_container" ]; then
  project_name=$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$first_container" 2>/dev/null || true)
fi
if [ -z "$project_name" ]; then
  project_name=$(basename "$PROJECT_ROOT" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-')
fi

$COMPOSE -f "$COMPOSE_FILE" down -v

remaining=$(docker ps -a -q --filter "label=com.docker.compose.project=$project_name")
if [ -n "$remaining" ]; then
  echo "compose containers still remain:" >&2
  docker ps -a --filter "label=com.docker.compose.project=$project_name" >&2
  exit 1
fi
