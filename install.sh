#!/usr/bin/env bash
# install.sh — one-shot setup for claude-local-memory
# Usage: bash install.sh [--no-launchd] [--embedding-provider mock|ollama|openai]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${REPO_DIR}/.venv"
DATA_DIR="${REPO_DIR}/data"
ENV_FILE="${REPO_DIR}/.env"
ENV_EXAMPLE="${REPO_DIR}/.env.example"
CLAUDE_MD="${HOME}/.claude/CLAUDE.md"

USE_LAUNCHD=1
EMBEDDING_PROVIDER="ollama"

# Parse flags
for arg in "$@"; do
  case "$arg" in
    --no-launchd) USE_LAUNCHD=0 ;;
    --embedding-provider=*) EMBEDDING_PROVIDER="${arg#*=}" ;;
    --embedding-provider) shift; EMBEDDING_PROVIDER="${1:-ollama}" ;;
  esac
done

log()  { printf '\033[0;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[0;32m    ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[0;33m  ! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[0;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ─── 1. Python version check ─────────────────────────────────────────────────
log "Checking Python"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  die "python3 not found — install Python 3.12+ and retry"
fi
PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(sys.version_info[:2])')"
if ! "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)'; then
  die "Python 3.12+ required, found $PY_VERSION"
fi
ok "Python $PY_VERSION"

# ─── 2. Virtual environment ───────────────────────────────────────────────────
log "Setting up Python venv at $VENV_DIR"
if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  ok "Created venv"
else
  ok "Venv already exists"
fi
PYTHON_BIN="${VENV_DIR}/bin/python"
PIP_BIN="${VENV_DIR}/bin/pip"

log "Installing Python dependencies"
"$PIP_BIN" install --quiet --upgrade pip
"$PIP_BIN" install --quiet -e "${REPO_DIR}"
ok "Dependencies installed"

# ─── 3. Data directory ───────────────────────────────────────────────────────
log "Creating data directory"
mkdir -p "$DATA_DIR"
ok "$DATA_DIR"

# ─── 4. Environment file ─────────────────────────────────────────────────────
log "Setting up .env"
if [ -f "$ENV_FILE" ]; then
  ok ".env already exists — skipping (edit manually if needed)"
else
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  # Replace placeholder db path with the actual repo path
  if [[ "$(uname)" == "Darwin" ]]; then
    sed -i '' "s|MEMORY_DB_PATH=.*|MEMORY_DB_PATH=${DATA_DIR}/memory.db|" "$ENV_FILE"
    sed -i '' "s|MEMORY_EMBEDDING_PROVIDER=.*|MEMORY_EMBEDDING_PROVIDER=${EMBEDDING_PROVIDER}|" "$ENV_FILE"
  else
    sed -i "s|MEMORY_DB_PATH=.*|MEMORY_DB_PATH=${DATA_DIR}/memory.db|" "$ENV_FILE"
    sed -i "s|MEMORY_EMBEDDING_PROVIDER=.*|MEMORY_EMBEDDING_PROVIDER=${EMBEDDING_PROVIDER}|" "$ENV_FILE"
  fi
  ok ".env created with db path: ${DATA_DIR}/memory.db"
fi

# ─── 5. Ollama model pull ─────────────────────────────────────────────────────
if [ "$EMBEDDING_PROVIDER" = "ollama" ]; then
  log "Checking Ollama"
  if ! command -v ollama >/dev/null 2>&1; then
    warn "Ollama not found — install it from https://ollama.com then re-run this script"
    warn "Or skip embeddings: bash install.sh --embedding-provider mock"
  else
    ok "Ollama found"

    # Read model name from generated .env (defaults to nomic-embed-text)
    OLLAMA_MODEL="nomic-embed-text"
    if [ -f "$ENV_FILE" ]; then
      _model="$(grep -E '^MEMORY_EMBEDDING_MODEL=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' | xargs)"
      [ -n "$_model" ] && OLLAMA_MODEL="$_model"
    fi

    # Ensure Ollama server is running before pulling
    OLLAMA_URL="${MEMORY_OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
    if ! curl -fsS --max-time 1.2 "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
      log "Starting Ollama server"
      nohup ollama serve >/dev/null 2>&1 &
      for _ in $(seq 1 30); do
        if curl -fsS --max-time 1 "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then break; fi
        sleep 0.5
      done
    fi

    if curl -fsS --max-time 1.2 "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
      if ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
        ok "${OLLAMA_MODEL} already present"
      else
        log "Pulling ${OLLAMA_MODEL} (embedding model)"
        ollama pull "$OLLAMA_MODEL"
        ok "${OLLAMA_MODEL} ready"
      fi
    else
      warn "Ollama server did not start — skipping model pull"
      warn "After installing Ollama, run: ollama pull ${OLLAMA_MODEL}"
    fi
  fi
fi

# ─── 6. Start services ───────────────────────────────────────────────────────
if [[ "$(uname)" == "Darwin" ]] && [ "$USE_LAUNCHD" = "1" ]; then
  log "Installing persistent launchd services (macOS)"
  # Patch the launchd install script to use this repo's venv python
  PYTHON_BIN="${VENV_DIR}/bin/python" MEMORY_ROOT_DIR="$REPO_DIR" \
    bash "${REPO_DIR}/ops/launchd_install.sh"
  ok "launchd services installed (auto-restart on crash + reboot)"
else
  log "Starting memory service (nohup mode)"
  PYTHON_BIN="${VENV_DIR}/bin/python" MEMORY_ROOT_DIR="$REPO_DIR" \
    bash "${REPO_DIR}/ops/start_local.sh"
  ok "Services started"
fi

# ─── 7. Health check ─────────────────────────────────────────────────────────
log "Waiting for API health"
API_URL="http://127.0.0.1:4815"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 1 "${API_URL}/v1/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

if ! curl -fsS --max-time 1 "${API_URL}/v1/health" >/dev/null 2>&1; then
  die "API did not come up at ${API_URL} — check logs in ${REPO_DIR}/runtime_logs/"
fi
ok "API healthy at ${API_URL}"

# ─── 8. Claude Code CLAUDE.md ────────────────────────────────────────────────
log "Configuring Claude Code integration"
HOOKS_DIR="${REPO_DIR}/hooks"

CLAUDE_MD_CONTENT="# Global Memory Service (All Projects)

This machine uses a shared local memory API for Claude Code sessions.

## Canonical Memory Service

- API base URL: \`http://127.0.0.1:4815\`
- Database path (service-side): \`${DATA_DIR}/memory.db\`
- Shared hook scripts: \`${HOOKS_DIR}/\`
- Project scope key: \`MEMORY_PROJECT_ID=\"\$PWD\"\` (absolute project path)

## Required Hook Routing

- \`SessionStart\` -> \`GET /v1/memory/bootstrap\`
- \`UserPromptSubmit\` -> \`POST /v1/memory/query\`
- \`SessionEnd\` -> \`POST /v1/memory/ingest/transcript\`

Do not use MCP checks as the default signal for memory connectivity. This setup is hook-based local API memory.

## Per-Project Hook Config Template

Put this in each project at \`.claude/settings.local.json\`:

\`\`\`json
{
  \"\\\$schema\": \"https://json.schemastore.org/claude-code-settings.json\",
  \"hooks\": {
    \"SessionStart\": [
      {
        \"matcher\": \"*\",
        \"hooks\": [
          {
            \"type\": \"command\",
            \"command\": \"bash ${HOOKS_DIR}/session_start.sh\"
          }
        ]
      }
    ],
    \"UserPromptSubmit\": [
      {
        \"hooks\": [
          {
            \"type\": \"command\",
            \"command\": \"MEMORY_PROJECT_ID=\\\"\\\$PWD\\\" MEMORY_API_URL=\\\"http://127.0.0.1:4815\\\" bash ${HOOKS_DIR}/user_prompt_submit.sh\"
          }
        ]
      }
    ],
    \"SessionEnd\": [
      {
        \"matcher\": \"*\",
        \"hooks\": [
          {
            \"type\": \"command\",
            \"command\": \"bash ${HOOKS_DIR}/session_end.sh\"
          }
        ]
      }
    ]
  }
}
\`\`\`

## Hook Auto-Bootstrap Rule (REQUIRED — Run at Every Session Start)

At the start of EVERY new conversation, before doing anything else:

1. Check if \`.claude/settings.local.json\` exists in \`\$PWD\`.
2. If it does NOT exist, create it immediately using the command below — no need to ask the user.
3. Then run \`bash ${REPO_DIR}/ops/ensure_service_running.sh\` to confirm the memory API is up.

Hooks are project-scoped. A global \`CLAUDE.md\` does not auto-apply hooks by itself — the settings file must exist in each project.

Bootstrap command (run from project root, auto-execute if file is missing):

\`\`\`bash
mkdir -p .claude && cat > .claude/settings.local.json <<'JSON'
{
  \"\\\$schema\": \"https://json.schemastore.org/claude-code-settings.json\",
  \"hooks\": {
    \"SessionStart\": [
      {
        \"matcher\": \"*\",
        \"hooks\": [
          {
            \"type\": \"command\",
            \"command\": \"bash ${HOOKS_DIR}/session_start.sh\"
          }
        ]
      }
    ],
    \"UserPromptSubmit\": [
      {
        \"hooks\": [
          {
            \"type\": \"command\",
            \"command\": \"MEMORY_PROJECT_ID=\\\"\\\$PWD\\\" MEMORY_API_URL=\\\"http://127.0.0.1:4815\\\" bash ${HOOKS_DIR}/user_prompt_submit.sh\"
          }
        ]
      }
    ],
    \"SessionEnd\": [
      {
        \"matcher\": \"*\",
        \"hooks\": [
          {
            \"type\": \"command\",
            \"command\": \"bash ${HOOKS_DIR}/session_end.sh\"
          }
        ]
      }
    ]
  }
}
JSON
\`\`\`

## Service Guard Rule (Required)

Before any memory-dependent action (bootstrap/query/ingest), ensure the memory API is running.

Preferred command:

\`\`\`bash
bash ${REPO_DIR}/ops/ensure_service_running.sh
\`\`\`

Install persistent services (once) so hooks do not lose memory when API/ollama crash:

\`\`\`bash
bash ${REPO_DIR}/ops/launchd_install.sh
\`\`\`

Equivalent inline check:

\`\`\`bash
curl -fsS http://127.0.0.1:4815/v1/health >/dev/null || \\
  bash ${REPO_DIR}/ops/start_local.sh
\`\`\`

Only proceed with memory operations after:

- health \`status\` is \`ok\`
- \`embedding_provider_ok\` is \`true\`

## Quick Checks

Health:

\`\`\`bash
curl -s http://127.0.0.1:4815/v1/health | jq
\`\`\`

Query memory for current project:

\`\`\`bash
curl -s -X POST http://127.0.0.1:4815/v1/memory/query \\
  -H 'Content-Type: application/json' \\
  -d \"{\\\"project_id\\\":\\\"\\\$PWD\\\",\\\"query\\\":\\\"last important memory\\\",\\\"k\\\":8,\\\"token_budget\\\":1400}\" | jq
\`\`\`

Conversation retrieval (clean transcript + summary):

\`\`\`bash
curl -s --get \"http://127.0.0.1:4815/v1/memory/conversation/<conversation_id>\" \\
  --data-urlencode \"project_id=\$PWD\" \\
  --data-urlencode \"limit=2000\" | jq
\`\`\`

## Default Response Guidance

If asked whether memory is connected:

- check hook configuration + API health first,
- state clearly when hook-based memory is active,
- if inactive, report exactly what is missing (API down, missing hooks, wrong \`project_id\`).
"

CLAUDE_MD_MARKER="<!-- claude-local-memory managed block -->"
mkdir -p "${HOME}/.claude"

if [ -f "$CLAUDE_MD" ]; then
  # Always back up first
  cp "$CLAUDE_MD" "${CLAUDE_MD}.backup"
  ok "Backup saved: ${CLAUDE_MD}.backup"

  if grep -qF "$CLAUDE_MD_MARKER" "$CLAUDE_MD" 2>/dev/null; then
    # Our block already present — replace it in-place between markers
    # Use awk to delete from start marker to end marker, then append fresh block
    awk "/${CLAUDE_MD_MARKER//\//\\/}/{found=1} found && /<!-- end claude-local-memory --/{found=0; next} !found{print}" \
      "$CLAUDE_MD" > "${CLAUDE_MD}.tmp" && mv "${CLAUDE_MD}.tmp" "$CLAUDE_MD"
    ok "~/.claude/CLAUDE.md: existing memory block removed for replacement"
  fi

  # Append our block (separated by a blank line from existing content)
  printf '\n%s\n%s\n%s\n' \
    "$CLAUDE_MD_MARKER" \
    "$CLAUDE_MD_CONTENT" \
    "<!-- end claude-local-memory -->" >> "$CLAUDE_MD"
  ok "~/.claude/CLAUDE.md: memory service section appended"
else
  # Fresh file — write with markers so future runs can update cleanly
  printf '%s\n%s\n%s\n' \
    "$CLAUDE_MD_MARKER" \
    "$CLAUDE_MD_CONTENT" \
    "<!-- end claude-local-memory -->" > "$CLAUDE_MD"
  ok "~/.claude/CLAUDE.md created"
fi

# ─── 9. Done ─────────────────────────────────────────────────────────────────
printf '\n'
printf '\033[0;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n'
printf '\033[0;32m  claude-local-memory installed successfully\033[0m\n'
printf '\033[0;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n'
printf '\n'
printf '  API:       %s\n' "${API_URL}"
printf '  Database:  %s/memory.db\n' "${DATA_DIR}"
printf '  Logs:      %s/runtime_logs/\n' "${REPO_DIR}"
printf '  Graph UI:  %s/ui/memory/graph\n' "${API_URL}"
printf '\n'
printf '  Next steps:\n'
printf '  1. Open a project and run:\n'
printf '       bash %s/ops/ensure_service_running.sh\n' "${REPO_DIR}"
printf '  2. ~/.claude/CLAUDE.md is configured — Claude Code picks it up automatically.\n'
printf '     To wire hooks for a specific project, run from that project root:\n'
printf '       bash %s/ops/ensure_service_running.sh\n' "${REPO_DIR}"
printf '     Then follow the bootstrap command in ~/.claude/CLAUDE.md to create\n'
printf '     .claude/settings.local.json in your project.\n'
printf '\n'
