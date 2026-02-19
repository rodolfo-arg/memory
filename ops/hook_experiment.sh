#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_PATH="${1:-$PWD}"
API_URL="${MEMORY_API_URL:-http://127.0.0.1:4815}"
PROJECT_ID="${MEMORY_PROJECT_ID:-$PROJECT_PATH}"
HOOK_DIR="${ROOT_DIR}/hooks"

require_bin() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "missing dependency: $cmd"
    exit 1
  fi
}

require_bin jq
require_bin curl

if [ ! -x "${HOOK_DIR}/session_start.sh" ] || [ ! -x "${HOOK_DIR}/user_prompt_submit.sh" ] || [ ! -x "${HOOK_DIR}/session_end.sh" ]; then
  echo "hook scripts are missing or not executable in ${HOOK_DIR}"
  exit 1
fi

echo "checking api health..."
curl -fsS "${API_URL}/v1/health" >/dev/null

marker="hook-smoke-$(date +%s)"
conversation_id="hook-exp-${marker}"
prompt="which marker command should i run ${marker}"
seed_content="Use pnpm prisma migrate deploy marker ${marker}"

echo "seeding memory via ingest/message..."
curl -fsS -X POST "${API_URL}/v1/memory/ingest/message" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg p "$PROJECT_ID" --arg c "$conversation_id" --arg content "$seed_content" \
      '{project_id:$p,conversation_id:$c,role:"assistant",content:$content}')" \
  >/dev/null

echo "running embed pass..."
curl -fsS -X POST "${API_URL}/v1/memory/ingest/chunks/embed" \
  -H 'Content-Type: application/json' \
  -d '{"batch_size":200}' >/dev/null

echo "validating SessionStart hook..."
session_start_out="$(
  printf '{}' | MEMORY_PROJECT_ID="$PROJECT_ID" MEMORY_API_URL="$API_URL" \
    bash "${HOOK_DIR}/session_start.sh"
)"
printf '%s\n' "$session_start_out" | jq . >/dev/null

echo "validating UserPromptSubmit hook..."
prompt_out="$(
  printf '%s' "$(jq -n --arg p "$prompt" '{prompt:$p}')" \
    | MEMORY_PROJECT_ID="$PROJECT_ID" MEMORY_API_URL="$API_URL" \
      bash "${HOOK_DIR}/user_prompt_submit.sh"
)"
if ! printf '%s' "$prompt_out" | jq -e --arg m "$marker" '.hookSpecificOutput.additionalContext | ascii_downcase | contains($m | ascii_downcase)' >/dev/null; then
  echo "UserPromptSubmit hook did not include expected marker context"
  echo "$prompt_out" | jq .
  exit 1
fi

echo "validating SessionEnd hook ingestion..."
tmp_transcript="$(mktemp)"
trap 'rm -f "$tmp_transcript"' EXIT
printf '{"role":"assistant","content":"Session end marker %s"}\n' "$marker" >"$tmp_transcript"

printf '%s' "$(jq -n --arg sid "$conversation_id" --arg tp "$tmp_transcript" '{session_id:$sid,transcript_path:$tp}')" \
  | MEMORY_PROJECT_ID="$PROJECT_ID" MEMORY_API_URL="$API_URL" \
    bash "${HOOK_DIR}/session_end.sh"

curl -fsS -X POST "${API_URL}/v1/memory/ingest/chunks/embed" \
  -H 'Content-Type: application/json' \
  -d '{"batch_size":200}' >/dev/null

session_end_query="$(curl -fsS -X POST "${API_URL}/v1/memory/query" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg p "$PROJECT_ID" --arg q "Session end marker ${marker}" '{project_id:$p,query:$q,k:5,token_budget:800}')")"

if ! printf '%s' "$session_end_query" | jq -e --arg m "$marker" 'any(.results[]?; (.snippet | ascii_downcase | contains($m | ascii_downcase)))' >/dev/null; then
  echo "SessionEnd hook ingest/query validation failed"
  echo "$session_end_query" | jq .
  exit 1
fi

echo "hook experiment passed"
echo "project_id=${PROJECT_ID}"
echo "marker=${marker}"
