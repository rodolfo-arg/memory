#!/usr/bin/env bash
set -euo pipefail

# Claude hook input arrives on stdin as JSON.
payload="$(cat || true)"
api_url="${MEMORY_API_URL:-http://127.0.0.1:4815}"
project_id="${MEMORY_PROJECT_ID:-$(basename "$PWD")}" 
ensure_script="${MEMORY_ENSURE_SCRIPT:-/Users/rodolfo/Developer/memory/ops/ensure_service_running.sh}"

if [ -x "$ensure_script" ]; then
  MEMORY_REQUIRE_EMBEDDING_HEALTH="${MEMORY_REQUIRE_EMBEDDING_HEALTH:-0}" \
    bash "$ensure_script" >/dev/null 2>&1 || true
fi

if ! command -v jq >/dev/null 2>&1; then
  printf '{}\n'
  exit 0
fi
project_id_encoded="$(jq -nr --arg v "$project_id" '$v|@uri')"

# Keep startup hook fast and fail-open.
response="$(
  curl -sS --max-time 0.25 \
    "$api_url/v1/memory/bootstrap?project_id=$project_id_encoded&token_budget=600&k=4" \
    2>/dev/null || true
)"

context="$(printf '%s' "$response" | jq -r '[.results[]?.snippet // empty][0:4] | join("\n")' 2>/dev/null || true)"

if [ -n "${context:-}" ]; then
  jq -n --arg c "Memory bootstrap:\n$context" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}}'
else
  printf '{}\n'
fi
