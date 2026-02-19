#!/usr/bin/env bash
set -euo pipefail

API_URL="${MEMORY_API_URL:-http://127.0.0.1:4815}"
PROJECT_ID="${MEMORY_PROJECT_ID:-${1:-$PWD}}"
LIMIT="${MEMORY_LAST_LIMIT:-${2:-5}}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi

curl -fsS --get "${API_URL}/v1/memory/latest" \
  --data-urlencode "project_id=${PROJECT_ID}" \
  --data-urlencode "limit=${LIMIT}" \
  --data-urlencode "include_chunks=true" \
  --data-urlencode "include_facts=true" \
  | jq
