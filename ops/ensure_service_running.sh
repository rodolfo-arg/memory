#!/usr/bin/env bash
set -euo pipefail

API_URL="${MEMORY_API_URL:-http://127.0.0.1:4815}"
START_SCRIPT="${MEMORY_START_SCRIPT:-/Users/rodolfo/Developer/memory/ops/start_local.sh}"
ROOT_DIR="${MEMORY_ROOT_DIR:-/Users/rodolfo/Developer/memory}"
ENSURE_OLLAMA_SCRIPT="${MEMORY_ENSURE_OLLAMA_SCRIPT:-${ROOT_DIR}/ops/ensure_ollama_running.sh}"
REQUIRE_EMBEDDING_HEALTH="${MEMORY_REQUIRE_EMBEDDING_HEALTH:-1}"
MEMORY_API_LAUNCHD_LABEL="${MEMORY_API_LAUNCHD_LABEL:-com.rodolfo.memory.api}"
MEMORY_API_LAUNCHD_PLIST="${MEMORY_API_LAUNCHD_PLIST:-/Users/rodolfo/Library/LaunchAgents/com.rodolfo.memory.api.plist}"
LAUNCH_DOMAIN="gui/$(id -u)"

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

health_json() {
  curl -fsS --max-time 1.2 "${API_URL}/v1/health" 2>/dev/null || true
}

api_reachable() {
  curl -fsS --max-time 1.2 "${API_URL}/v1/health" >/dev/null 2>&1
}

embedding_ok_from_health() {
  local payload="$1"
  if [ -z "$payload" ]; then
    return 1
  fi
  if command -v jq >/dev/null 2>&1; then
    local ok
    ok="$(printf '%s' "$payload" | jq -r '.embedding_provider_ok // "false"' 2>/dev/null || true)"
    [ "$ok" = "true" ]
    return
  fi
  printf '%s' "$payload" | tr -d '\n' | grep -q '"embedding_provider_ok":true'
}

kickstart_launchd_api() {
  if launchctl print "${LAUNCH_DOMAIN}/${MEMORY_API_LAUNCHD_LABEL}" >/dev/null 2>&1; then
    launchctl kickstart -k "${LAUNCH_DOMAIN}/${MEMORY_API_LAUNCHD_LABEL}" >/dev/null 2>&1 || true
    return 0
  fi
  if [ -f "$MEMORY_API_LAUNCHD_PLIST" ]; then
    launchctl bootstrap "$LAUNCH_DOMAIN" "$MEMORY_API_LAUNCHD_PLIST" >/dev/null 2>&1 || true
    launchctl kickstart -k "${LAUNCH_DOMAIN}/${MEMORY_API_LAUNCHD_LABEL}" >/dev/null 2>&1 || true
    return 0
  fi
  return 1
}

ensure_embedding_provider() {
  if ! provider_is_ollama; then
    return 0
  fi
  if [ ! -x "$ENSURE_OLLAMA_SCRIPT" ]; then
    echo "warning: ollama ensure script missing: $ENSURE_OLLAMA_SCRIPT" >&2
    return 1
  fi
  bash "$ENSURE_OLLAMA_SCRIPT"
}

load_env_file

if provider_is_ollama; then
  ensure_embedding_provider >/dev/null 2>&1 || true
fi

if api_reachable; then
  echo "memory service already running: ${API_URL}"
else
  echo "memory service unavailable at ${API_URL}; starting..."
  if ! kickstart_launchd_api; then
    bash "${START_SCRIPT}"
  fi
fi

for _ in $(seq 1 60); do
  if api_reachable; then
    break
  fi
  sleep 0.2
done

if ! api_reachable; then
  echo "memory service failed to start: ${API_URL}" >&2
  exit 1
fi

if provider_is_ollama; then
  health_payload="$(health_json)"
  if ! embedding_ok_from_health "$health_payload"; then
    ensure_embedding_provider >/dev/null 2>&1 || true
    for _ in $(seq 1 20); do
      health_payload="$(health_json)"
      if embedding_ok_from_health "$health_payload"; then
        break
      fi
      sleep 0.3
    done
  fi

  if [ "$REQUIRE_EMBEDDING_HEALTH" = "1" ] && ! embedding_ok_from_health "$(health_json)"; then
    echo "memory service started but embedding provider is degraded (ollama unavailable)" >&2
    exit 1
  fi
fi

echo "memory service started: ${API_URL}"
exit 0
