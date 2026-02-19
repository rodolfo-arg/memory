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
  exit 0
fi

session_id="$(printf '%s' "$payload" | jq -r '.session_id // .sessionId // ""' 2>/dev/null || true)"
transcript_path="$(printf '%s' "$payload" | jq -r '.transcript_path // .transcriptPath // ""' 2>/dev/null || true)"
conversation_id="${session_id:-$(date +%s)}"

# Session end ingestion is best-effort and must never block user workflow.
curl -sS --max-time 1.2 \
  -H 'Content-Type: application/json' \
  -X POST "$api_url/v1/memory/ingest/transcript" \
  -d "$(jq -n --arg p "$project_id" --arg s "$session_id" --arg t "$transcript_path" --arg c "$conversation_id" '{project_id:$p,session_id:$s,transcript_path:$t,conversation_id:$c,ingest_mode:"delta"}')" \
  >/dev/null 2>/dev/null || true

exit 0
