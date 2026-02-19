#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${MEMORY_ROOT_DIR:-/Users/rodolfo/Developer/memory}"
OLLAMA_URL="${MEMORY_OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
OLLAMA_LABEL="${MEMORY_OLLAMA_LAUNCHD_LABEL:-com.rodolfo.ollama}"
LAUNCH_DOMAIN="gui/$(id -u)"
PATH="${HOME}/.asdf/shims:${HOME}/.asdf/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

load_env_file() {
  local env_file="${ROOT_DIR}/.env"
  if [ -f "$env_file" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
}

provider_is_ollama() {
  local provider
  provider="$(printf '%s' "${MEMORY_EMBEDDING_PROVIDER:-mock}" | tr '[:upper:]' '[:lower:]' | xargs)"
  [ "$provider" = "ollama" ]
}

ollama_reachable() {
  curl -fsS --max-time 1.2 "${OLLAMA_URL}/api/tags" >/dev/null 2>&1
}

start_with_launchctl() {
  if ! launchctl print "${LAUNCH_DOMAIN}/${OLLAMA_LABEL}" >/dev/null 2>&1; then
    return 1
  fi
  launchctl kickstart -k "${LAUNCH_DOMAIN}/${OLLAMA_LABEL}" >/dev/null 2>&1 || true
  return 0
}

start_with_nohup() {
  if ! command -v ollama >/dev/null 2>&1; then
    echo "ollama binary not found in PATH" >&2
    return 1
  fi
  local log_dir="${ROOT_DIR}/runtime_logs/memory"
  mkdir -p "$log_dir"
  nohup ollama serve >"${log_dir}/ollama.log" 2>&1 &
  return 0
}

load_env_file

if ! provider_is_ollama; then
  echo "embedding provider is ${MEMORY_EMBEDDING_PROVIDER:-mock}; skipping ollama bootstrap"
  exit 0
fi

if ollama_reachable; then
  echo "ollama already running: ${OLLAMA_URL}"
  exit 0
fi

echo "ollama unavailable at ${OLLAMA_URL}; starting..."
if ! start_with_launchctl; then
  start_with_nohup
fi

for _ in $(seq 1 40); do
  if ollama_reachable; then
    echo "ollama started: ${OLLAMA_URL}"
    exit 0
  fi
  sleep 0.25
done

echo "ollama failed to start: ${OLLAMA_URL}" >&2
exit 1
