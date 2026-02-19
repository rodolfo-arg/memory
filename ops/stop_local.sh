#!/usr/bin/env bash
set -euo pipefail

PORT="${MEMORY_PORT:-4815}"
API_SUBSTR="-m uvicorn app.main:app --host 127.0.0.1 --port ${PORT}"
EMBED_SUBSTR="workers/embedding_worker.py"
COMPACT_SUBSTR="workers/compaction_worker.py"
LAUNCH_DOMAIN="gui/$(id -u)"

launchd_labels=(
  "com.rodolfo.memory.compaction-worker"
  "com.rodolfo.memory.embedding-worker"
  "com.rodolfo.memory.api"
  "com.rodolfo.ollama"
)

find_pids_by_substring() {
  local needle="$1"
  pgrep -f -- "$needle" || true
}

kill_by_substring() {
  local needle="$1"
  local label="$2"
  local pids
  pids="$(find_pids_by_substring "$needle" || true)"
  if [ -z "$pids" ]; then
    echo "${label}: none"
    return 0
  fi

  echo "${label}: stopping $(echo "$pids" | tr '\n' ' ')"
  while IFS= read -r pid; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done <<<"$pids"

  sleep 0.2
  local force_pids=""
  while IFS= read -r pid; do
    if [ -n "$pid" ] && ps -p "$pid" >/dev/null 2>&1; then
      force_pids="${force_pids}${pid}"$'\n'
    fi
  done <<<"$pids"

  if [ -n "$force_pids" ]; then
    echo "${label}: force killing $(echo "$force_pids" | tr '\n' ' ')"
    while IFS= read -r pid; do
      [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
    done <<<"$force_pids"
  fi
}

for label in "${launchd_labels[@]}"; do
  if launchctl print "${LAUNCH_DOMAIN}/${label}" >/dev/null 2>&1; then
    launchctl bootout "${LAUNCH_DOMAIN}/${label}" >/dev/null 2>&1 || true
    echo "launchd: booted out ${label}"
  fi
done

kill_by_substring "$EMBED_SUBSTR" "embedding-worker"
kill_by_substring "$COMPACT_SUBSTR" "compaction-worker"
kill_by_substring "$API_SUBSTR" "api"

# Best-effort fallback for listeners that are not using the expected command.
listener_pids="$(lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "${listener_pids:-}" ]; then
  echo "port-${PORT}: stopping listeners $(echo "$listener_pids" | tr '\n' ' ')"
  while IFS= read -r pid; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done <<<"$listener_pids"
fi

sleep 0.4

remaining="$(lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "${remaining:-}" ]; then
  echo "port-${PORT}: force killing $(echo "$remaining" | tr '\n' ' ')"
  while IFS= read -r pid; do
    [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
  done <<<"$remaining"
fi

echo "stop complete"
