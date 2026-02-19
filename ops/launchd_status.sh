#!/usr/bin/env bash
set -euo pipefail

API_URL="${MEMORY_API_URL:-http://127.0.0.1:4815}"
OLLAMA_URL="${MEMORY_OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
DOMAIN="gui/$(id -u)"

labels=(
  "com.rodolfo.ollama"
  "com.rodolfo.memory.api"
  "com.rodolfo.memory.embedding-worker"
  "com.rodolfo.memory.compaction-worker"
)

echo "launchd labels:"
for label in "${labels[@]}"; do
  if launchctl print "${DOMAIN}/${label}" >/tmp/memory_launchd_status.out 2>/tmp/memory_launchd_status.err; then
    pid="$(awk '/pid = /{print $3; exit}' /tmp/memory_launchd_status.out)"
    last_exit="$(awk '/last exit code = /{print $5; exit}' /tmp/memory_launchd_status.out)"
    state="$(awk -F'= ' '/state = /{print $2; exit}' /tmp/memory_launchd_status.out)"
    echo "  ${label}: loaded state=${state:-unknown} pid=${pid:-none} last_exit=${last_exit:-unknown}"
  else
    echo "  ${label}: not loaded"
  fi
done

rm -f /tmp/memory_launchd_status.out /tmp/memory_launchd_status.err

echo
echo "memory health:"
curl -fsS "${API_URL}/v1/health" || echo "unreachable: ${API_URL}"

echo
echo "ollama health:"
curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null && echo "ok: ${OLLAMA_URL}" || echo "unreachable: ${OLLAMA_URL}"
