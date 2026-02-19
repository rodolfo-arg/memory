CREATE TABLE IF NOT EXISTS conversations (
  conversation_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  transcript_path TEXT,
  started_at TEXT,
  ended_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
  message_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('user','assistant','tool','system')),
  content TEXT NOT NULL,
  token_count INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chunk_id TEXT NOT NULL UNIQUE,
  chunk_hash TEXT NOT NULL UNIQUE,
  message_id TEXT,
  project_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  chunk_text TEXT NOT NULL,
  chunk_type TEXT NOT NULL DEFAULT 'turn',
  importance REAL NOT NULL DEFAULT 0.0,
  archived INTEGER NOT NULL DEFAULT 0,
  source_file TEXT,
  source_span TEXT,
  source_path TEXT,
  source_url TEXT,
  source_mtime TEXT,
  source_hash TEXT,
  chunk_index INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT,
  raw_text TEXT,
  summary_text TEXT,
  trust_level TEXT NOT NULL DEFAULT 'untrusted',
  chunker_version TEXT NOT NULL DEFAULT 'chunker-v1',
  summarizer_version TEXT NOT NULL DEFAULT 'summarizer-v1',
  last_accessed_at TEXT,
  access_count INTEGER NOT NULL DEFAULT 0,
  user_vote REAL,
  auto_judgement REAL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(message_id) REFERENCES messages(message_id) ON DELETE CASCADE,
  FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_project_time ON chunks(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chunks_conv ON chunks(conversation_id);
CREATE INDEX IF NOT EXISTS idx_chunks_archived ON chunks(archived);
CREATE INDEX IF NOT EXISTS idx_chunks_source_hash ON chunks(source_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_source_path_mtime ON chunks(source_path, source_mtime);
CREATE INDEX IF NOT EXISTS idx_chunks_source_slot
ON chunks(project_id, source_path, source_url, conversation_id, chunk_type, chunk_index);
CREATE INDEX IF NOT EXISTS idx_chunks_project_archived_created ON chunks(project_id, archived, created_at);
CREATE INDEX IF NOT EXISTS idx_chunks_access ON chunks(project_id, access_count, last_accessed_at);
CREATE INDEX IF NOT EXISTS idx_chunks_trust_level ON chunks(project_id, trust_level);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  chunk_text,
  project_id UNINDEXED,
  chunk_type UNINDEXED,
  content='chunks',
  content_rowid='id',
  tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, chunk_text, project_id, chunk_type)
  VALUES (new.id, new.chunk_text, new.project_id, new.chunk_type);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, chunk_text, project_id, chunk_type)
  VALUES('delete', old.id, old.chunk_text, old.project_id, old.chunk_type);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, chunk_text, project_id, chunk_type)
  VALUES('delete', old.id, old.chunk_text, old.project_id, old.chunk_type);
  INSERT INTO chunks_fts(rowid, chunk_text, project_id, chunk_type)
  VALUES (new.id, new.chunk_text, new.project_id, new.chunk_type);
END;

CREATE TABLE IF NOT EXISTS chunk_embeddings (
  chunk_id TEXT PRIMARY KEY,
  model TEXT NOT NULL,
  dimensions INTEGER NOT NULL,
  embed_model_id TEXT,
  dim INTEGER,
  embed_model TEXT,
  embed_dim INTEGER,
  distance_metric TEXT,
  vector_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_lookup
ON chunk_embeddings(embed_model, embed_dim, distance_metric, chunk_id);

CREATE TABLE IF NOT EXISTS memory_facts (
  fact_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  fact_text TEXT NOT NULL,
  confidence REAL NOT NULL,
  source_chunk_id TEXT,
  status TEXT NOT NULL CHECK(status IN ('active','stale','revoked')),
  updated_at TEXT NOT NULL,
  FOREIGN KEY(source_chunk_id) REFERENCES chunks(chunk_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_facts_project ON memory_facts(project_id, status);

CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','queued','running','done','failed')),
  attempts INTEGER NOT NULL DEFAULT 0,
  run_after TEXT,
  lease_until TEXT,
  leased_by TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_lookup ON jobs(job_type, status, run_after);
CREATE INDEX IF NOT EXISTS idx_jobs_lease ON jobs(job_type, status, lease_until, run_after);

CREATE TABLE IF NOT EXISTS retrieval_logs (
  query_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  query_text TEXT NOT NULL,
  intent TEXT,
  latency_ms INTEGER,
  result_chunk_ids_json TEXT,
  ranking_json TEXT,
  feedback TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ingest_offsets (
  transcript_path TEXT PRIMARY KEY,
  last_line INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS metrics_counters (
  metric_key TEXT PRIMARY KEY,
  metric_value INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversation_summaries (
  conversation_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  summary_text TEXT NOT NULL,
  message_count INTEGER NOT NULL DEFAULT 0,
  summarizer_version TEXT NOT NULL DEFAULT 'summarizer-v1',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversation_summaries_project_updated
ON conversation_summaries(project_id, updated_at);

CREATE TABLE IF NOT EXISTS idempotency_keys (
  endpoint TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  response_json TEXT NOT NULL,
  status_code INTEGER NOT NULL DEFAULT 200,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TEXT NOT NULL,
  PRIMARY KEY(endpoint, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON idempotency_keys(expires_at);

CREATE TABLE IF NOT EXISTS endpoint_latencies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  endpoint TEXT NOT NULL,
  latency_ms REAL NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_endpoint_latencies_lookup
ON endpoint_latencies(endpoint, created_at);

CREATE TABLE IF NOT EXISTS retrieval_eval_runs (
  run_id TEXT PRIMARY KEY,
  dataset_name TEXT NOT NULL,
  k INTEGER NOT NULL,
  total_queries INTEGER NOT NULL,
  recall_at_k REAL NOT NULL,
  mrr REAL NOT NULL,
  citation_accuracy REAL NOT NULL,
  details_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_retrieval_eval_runs_created
ON retrieval_eval_runs(created_at);
