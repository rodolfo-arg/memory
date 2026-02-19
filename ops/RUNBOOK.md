# Operations Runbook

## Health checks

1. API status:

```bash
curl -s http://127.0.0.1:4815/v1/health | jq
```

2. Metrics:

```bash
curl -s http://127.0.0.1:4815/v1/metrics
```

3. Admin stats (API-first ops):

```bash
curl -s http://127.0.0.1:4815/v1/admin/stats | jq
# If MEMORY_ADMIN_TOKEN is set, add:
# -H "X-Admin-Token: $MEMORY_ADMIN_TOKEN"
```

4. Launchd service status:

```bash
bash /Users/rodolfo/Developer/memory/ops/launchd_status.sh
```

## API-first maintenance

1. Re-embed missing/model-mismatch vectors:

```bash
curl -s -X POST http://127.0.0.1:4815/v1/admin/reembed \
  -H 'Content-Type: application/json' \
  -d '{"scope":"missing_or_model_mismatch","limit":50000}' | jq
```

2. WAL checkpoint:

```bash
curl -s -X POST http://127.0.0.1:4815/v1/admin/checkpoint \
  -H 'Content-Type: application/json' \
  -d '{"mode":"TRUNCATE"}' | jq
```

3. Vacuum:

```bash
curl -s -X POST http://127.0.0.1:4815/v1/admin/vacuum \
  -H 'Content-Type: application/json' \
  -d '{"max_queued_jobs":0,"analyze":false}' | jq
```

## Backup

```bash
bash /Users/rodolfo/Developer/memory/ops/backup_db.sh
```

Recommended cadence:

- daily backup
- weekly restore drill

## Restore

```bash
bash /Users/rodolfo/Developer/memory/ops/restore_db.sh /Users/rodolfo/Developer/memory/backups/memory_YYYYMMDD_HHMMSS.db
```

## Worker operations

1. Embedding worker:

```bash
python /Users/rodolfo/Developer/memory/workers/embedding_worker.py
```

2. Compaction worker:

```bash
python /Users/rodolfo/Developer/memory/workers/compaction_worker.py
```

3. Preferred process lifecycle (prevents duplicate workers and port conflicts):

```bash
bash /Users/rodolfo/Developer/memory/ops/start_local.sh
bash /Users/rodolfo/Developer/memory/ops/stop_local.sh
```

4. Recommended persistent lifecycle (auto-start at login, auto-restart on crash):

```bash
bash /Users/rodolfo/Developer/memory/ops/launchd_install.sh
bash /Users/rodolfo/Developer/memory/ops/launchd_uninstall.sh
```

## Hook experiment

Validate end-to-end hook behavior for a target project:

```bash
bash /Users/rodolfo/Developer/memory/ops/hook_experiment.sh /Users/rodolfo/Developer/ai_trader_bot
```

Expected result:

- `hook experiment passed`
- retrieval includes the generated marker for both `UserPromptSubmit` and `SessionEnd` paths.

## Local graph visualization

1. Open the UI in browser:

```text
http://127.0.0.1:4815/ui/memory/graph?project_id=/Users/rodolfo/Developer/ai_trader_bot
```

2. Raw graph API:

```bash
curl -s "http://127.0.0.1:4815/v1/memory/graph?project_id=/Users/rodolfo/Developer/ai_trader_bot" | jq
```

## Last memory retrieval

1. Direct API:

```bash
curl -s --get "http://127.0.0.1:4815/v1/memory/latest" \
  --data-urlencode "project_id=/Users/rodolfo/Developer/ai_trader_bot" \
  --data-urlencode "limit=5" | jq
```

2. Helper script:

```bash
bash /Users/rodolfo/Developer/memory/ops/get_last_memory.sh /Users/rodolfo/Developer/ai_trader_bot 5
```

3. Filter by conversation:

```bash
curl -s --get "http://127.0.0.1:4815/v1/memory/latest" \
  --data-urlencode "project_id=/Users/rodolfo/Developer/ai_trader_bot" \
  --data-urlencode "conversation_id=<conversation_id>" \
  --data-urlencode "limit=10" \
  --data-urlencode "include_chunks=true" \
  --data-urlencode "include_facts=false" | jq
```

4. Full conversation with clean summary:

```bash
curl -s --get "http://127.0.0.1:4815/v1/memory/conversation/<conversation_id>" \
  --data-urlencode "project_id=/Users/rodolfo/Developer/ai_trader_bot" \
  --data-urlencode "limit=2000" | jq
```

## Failure policy

- If the memory API is down, hooks fail open and Claude workflow continues.
- Restart API and workers, then process pending embed jobs.

## SQL policy

- Direct SQL is emergency/debug only.
- Routine ingestion/retrieval/maintenance should use API endpoints.
