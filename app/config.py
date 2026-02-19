from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    memory_env: str = Field(default="dev", alias="MEMORY_ENV")
    memory_api_host: str = Field(default="127.0.0.1", alias="MEMORY_API_HOST")
    memory_api_port: int = Field(default=4815, alias="MEMORY_API_PORT")
    memory_db_path: str = Field(
        default="/Users/rodolfo/Developer/memory/data/memory.db", alias="MEMORY_DB_PATH"
    )
    memory_log_level: str = Field(default="INFO", alias="MEMORY_LOG_LEVEL")

    memory_retrieval_dense_k: int = Field(default=60, alias="MEMORY_RETRIEVAL_DENSE_K")
    memory_retrieval_bm25_k: int = Field(default=60, alias="MEMORY_RETRIEVAL_BM25_K")
    memory_retrieval_final_k: int = Field(default=10, alias="MEMORY_RETRIEVAL_FINAL_K")
    memory_retrieval_dense_weight: float = Field(default=0.95, alias="MEMORY_RETRIEVAL_DENSE_WEIGHT")
    memory_retrieval_lexical_weight: float = Field(default=1.05, alias="MEMORY_RETRIEVAL_LEXICAL_WEIGHT")
    memory_retrieval_backend: str = Field(default="sqlite", alias="MEMORY_RETRIEVAL_BACKEND")
    memory_query_token_budget: int = Field(default=1800, alias="MEMORY_QUERY_TOKEN_BUDGET")

    memory_embedding_provider: str = Field(default="mock", alias="MEMORY_EMBEDDING_PROVIDER")
    memory_embedding_model: str = Field(default="nomic-embed-text", alias="MEMORY_EMBEDDING_MODEL")
    memory_embed_distance_metric: str = Field(default="cosine", alias="MEMORY_EMBED_DISTANCE_METRIC")
    memory_ollama_base_url: str = Field(
        default="http://127.0.0.1:11434", alias="MEMORY_OLLAMA_BASE_URL"
    )
    memory_embedding_dimensions: int = Field(default=384, alias="MEMORY_EMBEDDING_DIMENSIONS")
    memory_chunker_version: str = Field(default="chunker-v1", alias="MEMORY_CHUNKER_VERSION")
    memory_summarizer_version: str = Field(default="summarizer-v1", alias="MEMORY_SUMMARIZER_VERSION")
    memory_tei_base_url: str = Field(default="http://127.0.0.1:8080", alias="MEMORY_TEI_BASE_URL")
    memory_openai_base_url: str = Field(
        default="https://api.openai.com/v1", alias="MEMORY_OPENAI_BASE_URL"
    )
    memory_openai_api_key: str = Field(default="", alias="MEMORY_OPENAI_API_KEY")
    memory_qdrant_url: str = Field(default="http://127.0.0.1:6333", alias="MEMORY_QDRANT_URL")
    memory_qdrant_collection: str = Field(default="memory_chunks", alias="MEMORY_QDRANT_COLLECTION")
    memory_qdrant_api_key: str = Field(default="", alias="MEMORY_QDRANT_API_KEY")
    memory_qdrant_timeout_seconds: float = Field(
        default=2.5, alias="MEMORY_QDRANT_TIMEOUT_SECONDS"
    )

    memory_episodic_ttl_days: int = Field(default=30, alias="MEMORY_EPISODIC_TTL_DAYS")
    memory_warm_ttl_days: int = Field(default=180, alias="MEMORY_WARM_TTL_DAYS")

    memory_enable_redaction: bool = Field(default=True, alias="MEMORY_ENABLE_REDACTION")
    memory_denylist_paths: str = Field(
        default=".env,.ssh,id_rsa,id_ed25519", alias="MEMORY_DENYLIST_PATHS"
    )
    memory_admin_token: str = Field(default="", alias="MEMORY_ADMIN_TOKEN")
    memory_idempotency_ttl_hours: int = Field(default=72, alias="MEMORY_IDEMPOTENCY_TTL_HOURS")
    memory_endpoint_latency_retention_days: int = Field(
        default=7, alias="MEMORY_ENDPOINT_LATENCY_RETENTION_DAYS"
    )
    memory_endpoint_latency_max_samples_per_endpoint: int = Field(
        default=5000, alias="MEMORY_ENDPOINT_LATENCY_MAX_SAMPLES_PER_ENDPOINT"
    )
    memory_ingest_batch_max_messages: int = Field(
        default=2000, alias="MEMORY_INGEST_BATCH_MAX_MESSAGES"
    )
    memory_embed_job_lease_seconds: int = Field(default=120, alias="MEMORY_EMBED_JOB_LEASE_SECONDS")
    memory_worker_id: str = Field(default="", alias="MEMORY_WORKER_ID")

    @property
    def db_path(self) -> Path:
        return Path(self.memory_db_path)

    @property
    def denylist_patterns(self) -> list[str]:
        return [part.strip().lower() for part in self.memory_denylist_paths.split(",") if part.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
