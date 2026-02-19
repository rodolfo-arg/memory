ALTER TABLE chunks ADD COLUMN trust_level TEXT NOT NULL DEFAULT 'untrusted';
ALTER TABLE chunks ADD COLUMN chunker_version TEXT NOT NULL DEFAULT 'chunker-v1';
ALTER TABLE chunks ADD COLUMN summarizer_version TEXT NOT NULL DEFAULT 'summarizer-v1';
ALTER TABLE chunks ADD COLUMN last_accessed_at TEXT;
ALTER TABLE chunks ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE chunks ADD COLUMN user_vote REAL;
ALTER TABLE chunks ADD COLUMN auto_judgement REAL;

CREATE INDEX IF NOT EXISTS idx_chunks_project_archived_created
ON chunks(project_id, archived, created_at);

CREATE INDEX IF NOT EXISTS idx_chunks_access
ON chunks(project_id, access_count, last_accessed_at);

CREATE INDEX IF NOT EXISTS idx_chunks_trust_level
ON chunks(project_id, trust_level);

ALTER TABLE chunk_embeddings ADD COLUMN embed_model TEXT;
ALTER TABLE chunk_embeddings ADD COLUMN embed_dim INTEGER;
ALTER TABLE chunk_embeddings ADD COLUMN distance_metric TEXT;

UPDATE chunk_embeddings
SET
  embed_model = COALESCE(embed_model, embed_model_id, model),
  embed_dim = COALESCE(embed_dim, dim, dimensions),
  distance_metric = COALESCE(distance_metric, 'cosine')
WHERE embed_model IS NULL
   OR embed_dim IS NULL
   OR distance_metric IS NULL;

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_lookup
ON chunk_embeddings(embed_model, embed_dim, distance_metric, chunk_id);

ALTER TABLE retrieval_logs ADD COLUMN ranking_json TEXT;
