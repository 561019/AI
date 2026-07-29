from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_EMBEDDING_MODEL_NAME = "BAAI/bge-base-zh-v1.5"
BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENV_FILES = (
    BACKEND_ROOT.parent / ".env",
    BACKEND_ROOT.parent / ".env.local",
    BACKEND_ROOT / ".env",
    BACKEND_ROOT / ".env.local",
)


class Settings(BaseSettings):
    app_name: str = "Intent Analysis Engine"
    app_version: str = "0.1.0"
    app_env: str = "local"
    api_prefix: str = "/api"

    database_url: str = "postgresql+psycopg://intent:intent@localhost:5432/intent_analysis"
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "intent_vectors"
    intent_capability_collection: str = "intent_capability_vectors"
    vector_backend: Literal["milvus", "local"] = "milvus"
    local_vector_store_path: Path = BACKEND_ROOT.parent / ".runtime" / "intent_capability_vectors.npz"

    model_api_url: str = "http://localhost:8001/v1"
    model_api_key: str = ""
    embedding_model: str = "embedding-model"
    embedding_dimension: int = Field(default=1024, gt=0)
    embedding_model_name: str = DEFAULT_EMBEDDING_MODEL_NAME
    embedding_local_files_only: bool = False
    bge_model_name: str = DEFAULT_EMBEDDING_MODEL_NAME
    bge_embedding_dimension: int = Field(default=768, gt=0)
    embedding_runtime: Literal["in_process", "worker"] = "in_process"
    bge_worker_host: str = "127.0.0.1"
    bge_worker_port: int = Field(default=8011, ge=1, le=65535)
    bge_keep_warm: bool = False
    bge_idle_timeout_seconds: float = Field(default=60, ge=0)
    bge_worker_startup_timeout_seconds: float = Field(default=15, gt=0)
    bge_worker_request_timeout_seconds: float = Field(default=180, gt=0)
    rerank_model: str = "rerank-model"
    llm_provider: Literal["deepseek", "openai", "mock"] = "mock"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "llm-model"
    llm_timeout_seconds: float = Field(default=120, gt=0)

    rule_threshold: float = 0.9
    enable_semantic_matching: bool = True
    semantic_threshold: float = 0.50
    llm_confidence_threshold: float = Field(default=0.70, ge=0, le=1)
    implicit_task_confidence_threshold: float = Field(default=0.70, ge=0, le=1)
    implicit_fallback_batch_characters: int = Field(default=8000, ge=1000, le=50000)
    conversation_history_limit: int = Field(default=20, ge=1, le=200)
    long_text_chunk_size: int = Field(default=2000, ge=200, le=20000)
    long_text_chunk_overlap: int = Field(default=200, ge=0, le=5000)
    long_text_activation_length: int = Field(default=120, ge=1, le=10000)
    long_text_activation_sentences: int = Field(default=3, ge=1, le=100)

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def milvus_collection_name(self) -> str:
        return self.milvus_collection

    @property
    def intent_capability_collection_name(self) -> str:
        return self.intent_capability_collection

    @model_validator(mode="after")
    def apply_legacy_bge_model_name(self) -> "Settings":
        if (
            self.embedding_model_name == DEFAULT_EMBEDDING_MODEL_NAME
            and self.bge_model_name != DEFAULT_EMBEDDING_MODEL_NAME
        ):
            self.embedding_model_name = self.bge_model_name
        return self


settings = Settings()
