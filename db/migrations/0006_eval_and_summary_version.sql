ALTER TABLE conversation_summaries
ADD COLUMN summarizer_version TEXT NOT NULL DEFAULT 'summarizer-v1';

CREATE INDEX IF NOT EXISTS idx_chunks_source_slot
ON chunks(project_id, source_path, source_url, conversation_id, chunk_type, chunk_index);

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
