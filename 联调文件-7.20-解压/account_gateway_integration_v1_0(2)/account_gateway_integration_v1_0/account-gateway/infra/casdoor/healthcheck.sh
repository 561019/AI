#!/bin/sh
set -eu

CASDOOR_HEALTH_URL="${CASDOOR_HEALTH_URL:-http://127.0.0.1:8000/api/health}"

status_code="$(wget -q -O - "$CASDOOR_HEALTH_URL" 2>/dev/null | head -1)"
test "$status_code" = "ok"
