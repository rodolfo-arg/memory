# claude-local-memory

A local-first, persistent memory layer for Claude Code. Stores and retrieves conversation context across sessions using a lightweight FastAPI service, SQLite + FTS5 for hybrid retrieval, and Ollama for local embeddings — no external databases or cloud services required.

---

## How It Works

```
Claude Code session
       │
       ├─ SessionStart     → GET  /v1/memory/bootstrap     → injects recent context
       ├─ UserPromptSubmit → POST /v1/memory/query          → injects top-k relevant chunks
       └─ SessionEnd       → POST /v1/memory/ingest/transcript → stores transcript delta
```

Claude Code fires shell hooks at three lifecycle events. Each hook calls the local memory API, which performs hybrid retrieval (dense vectors + BM25 lexical search) and returns relevant context prepended to Claude's context window. Memory is scoped per project by absolute path.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ | `python3 --version` |
| [Ollama](https://ollama.com) | any | For local embeddings (recommended) |
| [Claude Code](https://claude.ai/code) | any | The CLI this integrates with |
| `curl`, `jq` | any | For health checks |

> **No GPU required.** `nomic-embed-text` (384-dim) runs efficiently on CPU.

---

## Quick Install

```bash
git clone <this-repo> ~/Developer/memory
cd ~/Developer/memory
bash install.sh
```

That single command:

1. Creates a Python venv and installs all dependencies
2. Generates `.env` with correct absolute paths for your machine
3. Pulls `nomic-embed-text` via Ollama
4. Installs and starts the memory API + background workers (launchd on macOS, nohup elsewhere)
5. Writes `~/.claude/CLAUDE.md` with your hook paths — Claude Code reads this automatically

### Install Options

```bash
bash install.sh --no-launchd                    # use nohup instead of launchd (macOS)
bash install.sh --embedding-provider=mock       # no embeddings, fast for testing
bash install.sh --embedding-provider=openai     # OpenAI embeddings (set MEMORY_OPENAI_API_KEY in .env)
```

---

## Claude Code Integration

The installer writes `~/.claude/CLAUDE.md` with your machine-specific hook paths. Below is the canonical reference for what that file contains and how it works. Replace `<MEMORY_DIR>` with your actual install path (e.g. `~/Developer/memory`).

---

### `~/.claude/CLAUDE.md` Reference

#### Canonical Memory Service

- API base URL: `http://127.0.0.1:4815`
- Database path: `<MEMORY_DIR>/data/memory.db`
- Hook scripts: `<MEMORY_DIR>/hooks/`
- Project scope key: `MEMORY_PROJECT_ID="$PWD"` (absolute project path)

#### Required Hook Routing

- `SessionStart` → `GET /v1/memory/bootstrap`
- `UserPromptSubmit` → `POST /v1/memory/query`
- `SessionEnd` → `POST /v1/memory/ingest/transcript`

Do not use MCP checks as the default signal for memory connectivity. This setup is hook-based local API memory.

#### Per-Project Hook Config

Put this in each project at `.claude/settings.local.json`:

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash <MEMORY_DIR>/hooks/session_start.sh"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "MEMORY_PROJECT_ID=\"$PWD\" MEMORY_API_URL=\"http://127.0.0.1:4815\" bash <MEMORY_DIR>/hooks/user_prompt_submit.sh"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash <MEMORY_DIR>/hooks/session_end.sh"
          }
        ]
      }
    ]
  }
}
```

#### Hook Bootstrap Rule (Required)

Hooks are project-scoped. A global `CLAUDE.md` does not auto-apply hooks by itself.

If `.claude/settings.local.json` is missing in a project, create it before any memory-dependent task. Bootstrap command (run from that project's root):

```bash
mkdir -p .claude && cat > .claude/settings.local.json <<'JSON'
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash <MEMORY_DIR>/hooks/session_start.sh"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "MEMORY_PROJECT_ID=\"$PWD\" MEMORY_API_URL=\"http://127.0.0.1:4815\" bash <MEMORY_DIR>/hooks/user_prompt_submit.sh"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash <MEMORY_DIR>/hooks/session_end.sh"
          }
        ]
      }
    ]
  }
}
JSON
```

#### Service Guard Rule (Required)

Before any memory-dependent action, ensure the API is running:

```bash
bash <MEMORY_DIR>/ops/ensure_service_running.sh
```

Install persistent services (once) so hooks survive API or Ollama crashes:

```bash
bash <MEMORY_DIR>/ops/launchd_install.sh
```

Equivalent inline check:

```bash
curl -fsS http://127.0.0.1:4815/v1/health >/dev/null || \
  bash <MEMORY_DIR>/ops/start_local.sh
```

Only proceed with memory operations after:
- health `status` is `ok`
- `embedding_provider_ok` is `true`

#### Quick Checks

```bash
# Health
curl -s http://127.0.0.1:4815/v1/health | jq

# Query memory for current project
curl -s -X POST http://127.0.0.1:4815/v1/memory/query \
  -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"$PWD\",\"query\":\"last important memory\",\"k\":8,\"token_budget\":1400}" | jq

# Retrieve a conversation transcript
curl -s --get "http://127.0.0.1:4815/v1/memory/conversation/<conversation_id>" \
  --data-urlencode "project_id=$PWD" \
  --data-urlencode "limit=2000" | jq
```

#### Default Response Guidance

If asked whether memory is connected:
- Check hook configuration + API health first
- State clearly when hook-based memory is active
- If inactive, report exactly what is missing (API down, missing hooks, wrong `project_id`)

---

## Configuration

Edit `.env` in the repo root. Key options:

| Variable | Default | Description |
|---|---|---|
| `MEMORY_API_PORT` | `4815` | API listen port |
| `MEMORY_DB_PATH` | `data/memory.db` | SQLite database path |
| `MEMORY_EMBEDDING_PROVIDER` | `ollama` | `ollama`, `mock`, `openai`, `tei` |
| `MEMORY_EMBEDDING_MODEL` | `nomic-embed-text` | Ollama model name |
| `MEMORY_EPISODIC_TTL_DAYS` | `30` | Days before episodic memory compaction |
| `MEMORY_WARM_TTL_DAYS` | `180` | Days before warm memory expiry |
| `MEMORY_ENABLE_REDACTION` | `true` | Strip secrets from ingested text |
| `MEMORY_ADMIN_TOKEN` | _(empty)_ | Optional token to protect admin endpoints |

See `.env.example` for the full reference.

---

## Graph UI

A force-directed graph visualizing all stored memories:

```
http://127.0.0.1:4815/ui/memory/graph?project_id=<absolute-project-path>
```

Features:
- Node types: conversations, chunks, facts
- Live refresh mode (auto-polls at configurable interval)
- Filter flyout: by type, importance, confidence, date range
- Settings flyout: node limits, render mode
- Click a node → metadata popover with details
- Timeline list view (keyboard shortcut: `t`)

Query parameters: `mode=2d`, `live=1`, `every=4` (seconds)

---

## Service Management

```bash
# Start (idempotent — safe to run repeatedly)
bash ops/ensure_service_running.sh

# Stop all processes
bash ops/stop_local.sh

# Persistent startup at login (macOS only)
bash ops/launchd_install.sh

# Check launchd status (macOS)
bash ops/launchd_status.sh

# Preflight check (all systems)
bash ops/preflight_check.sh
```

Logs:
```bash
# macOS launchd
tail -f runtime_logs/launchd/memory-api.out.log
tail -f runtime_logs/launchd/embedding-worker.out.log

# nohup
tail -f runtime_logs/memory/api.log
tail -f runtime_logs/memory/embedding_worker.log
```

---

## API Surface

```
POST /v1/memory/ingest/message
POST /v1/memory/ingest/messages/batch
POST /v1/memory/ingest/transcript
POST /v1/memory/ingest/chunks/embed
POST /v1/memory/query
POST /v1/memory/query/batch
GET  /v1/memory/latest
GET  /v1/memory/conversation/{conversation_id}
GET  /v1/memory/bootstrap
POST /v1/memory/facts/upsert
POST /v1/memory/chunks/feedback
POST /v1/memory/compact
GET  /v1/admin/stats
POST /v1/admin/reembed
POST /v1/admin/resummarize
POST /v1/admin/checkpoint
POST /v1/admin/vacuum
GET  /v1/health
GET  /v1/metrics
```

### Recency retrieval

```bash
curl -s --get "http://127.0.0.1:4815/v1/memory/latest" \
  --data-urlencode "project_id=$PWD" \
  --data-urlencode "limit=5" | jq
```

Helper script: `bash ops/get_last_memory.sh "$PWD" 5`

---

## Architecture

```
memory/
├── app/               # FastAPI application
│   ├── main.py        # API entrypoint
│   ├── routers/       # Endpoint handlers
│   └── ui_graph.py    # Graph UI + static assets
├── workers/
│   ├── embedding_worker.py    # Async embedding job processor
│   └── compaction_worker.py  # Memory compaction / TTL cleanup
├── hooks/             # Claude Code lifecycle hook scripts
│   ├── session_start.sh
│   ├── user_prompt_submit.sh
│   └── session_end.sh
├── ops/               # Service management scripts
├── data/              # SQLite database (gitignored)
├── install.sh         # One-shot installer
└── .env               # Local config (gitignored)
```

**Storage:** SQLite with WAL mode + FTS5 for BM25 lexical search. Embedding vectors stored as JSON blobs. Qdrant optional for large deployments.

**Retrieval:** Hybrid — dense cosine similarity (top-60) + BM25 lexical (top-60), RRF fusion, final top-10 returned to Claude. Explainability payloads written to `retrieval_logs`.

**Workers:** Two background processes run alongside the API. The embedding worker processes queued chunks; the compaction worker expires stale memory by TTL. Both auto-restart under launchd.

**SQLite hardening:** WAL mode, `busy_timeout=5000`, per-request connections, embed queue with lease semantics (`pending|running|done|failed`), expired leases auto-reclaimed.

---

## Troubleshooting

**API not starting**
```bash
curl -s http://127.0.0.1:4815/v1/health | jq
tail -n 50 runtime_logs/memory/api.log
```

**Embedding provider degraded**
```bash
ollama list
ollama pull nomic-embed-text
bash ops/ensure_ollama_running.sh
```

**Hooks not firing**
- Confirm `.claude/settings.local.json` exists in your project with correct absolute paths
- Run `claude /doctor` in Claude Code to check hook registration

**Memory not persisting between sessions**
- Check `SessionEnd` hook is configured correctly
- Verify API was reachable when the session ended

**Port conflict — change port**
```bash
# In .env
MEMORY_API_PORT=4816
# Then update hook commands to use the new port
```

**Validate hooks end-to-end**
```bash
bash ops/hook_experiment.sh "$PWD"
```

---

## Uninstall

```bash
bash ops/stop_local.sh
bash ops/launchd_uninstall.sh   # macOS only
rm -rf ~/Developer/memory
rm ~/.claude/CLAUDE.md           # if no longer needed
```

---

## Development

```bash
# Run API in dev mode
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 4815 --reload

# Run tests
.venv/bin/pytest

# Load smoke test
python tests/load/load_query_smoke.py --requests 200 --concurrency 20

# Retrieval eval harness
python ops/eval_harness.py \
  --dataset tests/eval/golden_set.sample.json \
  --dataset-name local-golden-v1 \
  --k 8

# Database backup (WAL-safe)
bash ops/backup_db.sh
```
