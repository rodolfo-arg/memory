#!/usr/bin/env bash
set -euo pipefail

LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"

labels=(
  "com.rodolfo.ollama"
  "com.rodolfo.memory.api"
  "com.rodolfo.memory.embedding-worker"
  "com.rodolfo.memory.compaction-worker"
)

for label in "${labels[@]}"; do
  launchctl bootout "${DOMAIN}/${label}" >/dev/null 2>&1 || true
  rm -f "${LAUNCH_AGENTS_DIR}/${label}.plist"
done

echo "removed launchd services:"
for label in "${labels[@]}"; do
  echo "  - ${label}"
done
