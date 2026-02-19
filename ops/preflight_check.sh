#!/usr/bin/env bash
set -euo pipefail

API_URL="${MEMORY_API_URL:-http://127.0.0.1:4815}"
ADMIN_TOKEN="${MEMORY_ADMIN_TOKEN:-}"

curl -fsS "$API_URL/v1/health" >/dev/null
curl -fsS "$API_URL/v1/metrics" >/dev/null
if [ -n "$ADMIN_TOKEN" ]; then
  curl -fsS -H "X-Admin-Token: $ADMIN_TOKEN" "$API_URL/v1/admin/stats" >/dev/null
else
  curl -fsS "$API_URL/v1/admin/stats" >/dev/null
fi

echo "preflight ok"
