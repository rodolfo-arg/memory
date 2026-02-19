#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT_DIR}/runtime_logs/memory"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
LAUNCH_DOMAIN="gui/$(id -u)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [ -f "${ROOT_DIR}/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  source "${ROOT_DIR}/.env"
  set +a
fi
HOST="${MEMORY_HOST:-${MEMORY_API_HOST:-127.0.0.1}}"
PORT="${MEMORY_PORT:-${MEMORY_API_PORT:-4815}}"
API_URL="http://${HOST}:${PORT}"
PROJECT_ID="${MEMORY_PROJECT_ID:-memory}"
CLEAN_START="${MEMORY_CLEAN_START:-1}"

mkdir -p "$LOG_DIR"

show_pid_status() {
  local label="$1"
  local pid_file="$2"
  if [ ! -f "$pid_file" ]; then
    echo "${label}: none"
    return 0
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [ -z "$pid" ]; then
    echo "${label}: none"
    return 0
  fi

  if ps -p "$pid" >/dev/null 2>&1; then
    local cmd
    cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    echo "${label}: ${pid} ${cmd}"
  else
    echo "${label}: dead (pid ${pid})"
  fi
}

bootstrap_label() {
  local label="$1"
  local plist_path="${LAUNCH_AGENTS_DIR}/${label}.plist"
  if [ ! -f "$plist_path" ]; then
    return 0
  fi
  launchctl bootstrap "$LAUNCH_DOMAIN" "$plist_path" >/dev/null 2>&1 || true
  launchctl kickstart -k "${LAUNCH_DOMAIN}/${label}" >/dev/null 2>&1 || true
}

if [ -f "${LAUNCH_AGENTS_DIR}/com.rodolfo.memory.api.plist" ]; then
  if [ "$CLEAN_START" = "1" ]; then
    bash "${ROOT_DIR}/ops/stop_local.sh"
  fi
  bootstrap_label "com.rodolfo.ollama"
  bootstrap_label "com.rodolfo.memory.api"
  bootstrap_label "com.rodolfo.memory.embedding-worker"
  bootstrap_label "com.rodolfo.memory.compaction-worker"
  for _ in $(seq 1 40); do
    if curl -fsS "${API_URL}/v1/health" >/dev/null 2>&1; then
      break
    fi
    sleep 0.25
  done
  if ! curl -fsS "${API_URL}/v1/health" >/dev/null 2>&1; then
    echo "api failed to start on ${API_URL} via launchd"
    exit 1
  fi
  echo "start complete (launchd)"
  exit 0
fi

if [ "$CLEAN_START" = "1" ]; then
  bash "${ROOT_DIR}/ops/stop_local.sh"
fi

if [ "$(printf '%s' "${MEMORY_EMBEDDING_PROVIDER:-mock}" | tr '[:upper:]' '[:lower:]')" = "ollama" ]; then
  bash "${ROOT_DIR}/ops/ensure_ollama_running.sh" >/dev/null 2>&1 || true
fi

echo "starting api on ${API_URL}"
(
  cd "$ROOT_DIR"
  nohup "$PYTHON_BIN" -m uvicorn app.main:app --host "$HOST" --port "$PORT" \
    >"${LOG_DIR}/api.log" 2>&1 &
  echo "$!" >"${LOG_DIR}/api.pid"
)

echo "starting embedding worker"
(
  cd "$ROOT_DIR"
  nohup "$PYTHON_BIN" workers/embedding_worker.py \
    >"${LOG_DIR}/embedding_worker.log" 2>&1 &
  echo "$!" >"${LOG_DIR}/embedding_worker.pid"
)

echo "starting compaction worker"
(
  cd "$ROOT_DIR"
  MEMORY_PROJECT_ID="$PROJECT_ID" nohup "$PYTHON_BIN" workers/compaction_worker.py \
    >"${LOG_DIR}/compaction_worker.log" 2>&1 &
  echo "$!" >"${LOG_DIR}/compaction_worker.pid"
)

for _ in $(seq 1 40); do
  if curl -fsS "${API_URL}/v1/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

if ! curl -fsS "${API_URL}/v1/health" >/dev/null 2>&1; then
  echo "api failed to start on ${API_URL}; tailing api log:"
  tail -n 50 "${LOG_DIR}/api.log" || true
  exit 1
fi

show_pid_status "api" "${LOG_DIR}/api.pid"
show_pid_status "embedding-worker" "${LOG_DIR}/embedding_worker.pid"
show_pid_status "compaction-worker" "${LOG_DIR}/compaction_worker.pid"
echo "start complete"
