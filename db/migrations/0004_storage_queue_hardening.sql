PRAGMA foreign_keys = OFF;

ALTER TABLE chunks ADD COLUMN raw_text TEXT;
ALTER TABLE chunks ADD COLUMN summary_text TEXT;
ALTER TABLE chunks ADD COLUMN source_path TEXT;
ALTER TABLE chunks ADD COLUMN source_url TEXT;
ALTER TABLE chunks ADD COLUMN source_mtime TEXT;
ALTER TABLE chunks ADD COLUMN source_hash TEXT;
ALTER TABLE chunks ADD COLUMN chunk_index INTEGER NOT NULL DEFAULT 0;

UPDATE chunks
SET
  raw_text = COALESCE(raw_text, chunk_text),
  summary_text = COALESCE(summary_text, substr(chunk_text, 1, 512)),
  source_path = COALESCE(source_path, source_file)
WHERE raw_text IS NULL
   OR summary_text IS NULL
   OR source_path IS NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_source_hash ON chunks(source_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_source_path_mtime ON chunks(source_path, source_mtime);

ALTER TABLE chunk_embeddings ADD COLUMN embed_model_id TEXT;
ALTER TABLE chunk_embeddings ADD COLUMN dim INTEGER;

UPDATE chunk_embeddings
SET
  embed_model_id = COALESCE(embed_model_id, model),
  dim = COALESCE(dim, dimensions)
WHERE embed_model_id IS NULL
   OR dim IS NULL;

CREATE TABLE jobs_new (
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

INSERT INTO jobs_new(
  job_id, job_type, payload_json, status, attempts, run_after, lease_until, leased_by, last_error, created_at, updated_at
)
SELECT
  job_id,
  job_type,
  payload_json,
  CASE WHEN status = 'queued' THEN 'pending' ELSE status END AS status,
  attempts,
  run_after,
  NULL AS lease_until,
  NULL AS leased_by,
  last_error,
  created_at,
  updated_at
FROM jobs;

DROP TABLE jobs;
ALTER TABLE jobs_new RENAME TO jobs;

CREATE INDEX IF NOT EXISTS idx_jobs_lookup ON jobs(job_type, status, run_after);
CREATE INDEX IF NOT EXISTS idx_jobs_lease ON jobs(job_type, status, lease_until, run_after);

PRAGMA foreign_keys = ON;
