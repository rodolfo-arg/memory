#!/usr/bin/env bash
set -euo pipefail

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

prompt="$(printf '%s' "$payload" | jq -r '.prompt // .input.prompt // .user_prompt // ""' 2>/dev/null || true)"
if [ -z "${prompt:-}" ]; then
  printf '{}\n'
  exit 0
fi

response="$(
  curl -sS --max-time 0.30 \
    -H 'Content-Type: application/json' \
    -X POST "$api_url/v1/memory/query" \
    -d "$(jq -n --arg p "$project_id" --arg q "$prompt" '{project_id:$p,query:$q,intent:"auto",k:8,token_budget:1400}')" \
    2>/dev/null || true
)"

context="$(printf '%s' "$response" | jq -r '[.results[]?.snippet // empty][0:8] | join("\n")' 2>/dev/null || true)"

if [ -n "${context:-}" ]; then
  jq -n --arg c "Relevant memory:\n$context" '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$c}}'
else
  printf '{}\n'
fi
