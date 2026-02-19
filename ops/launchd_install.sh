#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${MEMORY_ROOT_DIR:-/Users/rodolfo/Developer/memory}"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
LOG_DIR="${ROOT_DIR}/runtime_logs/launchd"
DOMAIN="gui/$(id -u)"
PATH_VALUE="${HOME}/.asdf/shims:${HOME}/.asdf/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

if [ -f "${ROOT_DIR}/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  source "${ROOT_DIR}/.env"
  set +a
fi

API_HOST="${MEMORY_API_HOST:-127.0.0.1}"
API_PORT="${MEMORY_API_PORT:-4815}"

mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR"

write_plist() {
  local label="$1"
  local command="$2"
  local stdout_path="$3"
  local stderr_path="$4"
  local plist_path="${LAUNCH_AGENTS_DIR}/${label}.plist"

  cat >"$plist_path" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>${command}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT_DIR}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>5</integer>
  <key>StandardOutPath</key>
  <string>${stdout_path}</string>
  <key>StandardErrorPath</key>
  <string>${stderr_path}</string>
</dict>
</plist>
PLIST
}

bootstrap_label() {
  local label="$1"
  local plist_path="${LAUNCH_AGENTS_DIR}/${label}.plist"
  launchctl bootout "${DOMAIN}/${label}" >/dev/null 2>&1 || true
  if ! launchctl bootstrap "$DOMAIN" "$plist_path" >/dev/null 2>&1; then
    if ! launchctl print "${DOMAIN}/${label}" >/dev/null 2>&1; then
      echo "warning: failed to bootstrap ${label}" >&2
    fi
  fi
  launchctl kickstart -k "${DOMAIN}/${label}" >/dev/null 2>&1 || true
}

wait_for_label() {
  local label="$1"
  for _ in $(seq 1 20); do
    if launchctl print "${DOMAIN}/${label}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

OLLAMA_LABEL="com.rodolfo.ollama"
API_LABEL="com.rodolfo.memory.api"
EMBED_LABEL="com.rodolfo.memory.embedding-worker"
COMPACT_LABEL="com.rodolfo.memory.compaction-worker"

write_plist \
  "$OLLAMA_LABEL" \
  "export PATH='${PATH_VALUE}'; exec ollama serve" \
  "${LOG_DIR}/ollama.out.log" \
  "${LOG_DIR}/ollama.err.log"

write_plist \
  "$API_LABEL" \
  "export PATH='${PATH_VALUE}'; cd '${ROOT_DIR}'; if [ -f '.env' ]; then set -a; source '.env'; set +a; fi; exec python3 -m uvicorn app.main:app --host '${API_HOST}' --port '${API_PORT}'" \
  "${LOG_DIR}/memory-api.out.log" \
  "${LOG_DIR}/memory-api.err.log"

write_plist \
  "$EMBED_LABEL" \
  "export PATH='${PATH_VALUE}'; cd '${ROOT_DIR}'; if [ -f '.env' ]; then set -a; source '.env'; set +a; fi; exec python3 workers/embedding_worker.py" \
  "${LOG_DIR}/embedding-worker.out.log" \
  "${LOG_DIR}/embedding-worker.err.log"

write_plist \
  "$COMPACT_LABEL" \
  "export PATH='${PATH_VALUE}'; cd '${ROOT_DIR}'; if [ -f '.env' ]; then set -a; source '.env'; set +a; fi; exec python3 workers/compaction_worker.py" \
  "${LOG_DIR}/compaction-worker.out.log" \
  "${LOG_DIR}/compaction-worker.err.log"

bootstrap_label "$OLLAMA_LABEL"
bootstrap_label "$API_LABEL"
bootstrap_label "$EMBED_LABEL"
bootstrap_label "$COMPACT_LABEL"

for label in "$OLLAMA_LABEL" "$API_LABEL" "$EMBED_LABEL" "$COMPACT_LABEL"; do
  if ! wait_for_label "$label"; then
    echo "error: launchd label is not loaded: ${label}" >&2
    exit 1
  fi
done

echo "installed launchd services:"
echo "  - ${OLLAMA_LABEL}"
echo "  - ${API_LABEL}"
echo "  - ${EMBED_LABEL}"
echo "  - ${COMPACT_LABEL}"
echo "log directory: ${LOG_DIR}"
