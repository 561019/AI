from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ChunkSettings:
    target_tokens: int = 600
    max_tokens: int = 800
    min_tokens: int = 120
    overlap_tokens: int = 80
    embed_review_required: bool = False
    strategy_version: str = "semantic-layout-table-v1"

    def validate(self) -> None:
        if not 0 < self.min_tokens <= self.target_tokens <= self.max_tokens:
            raise ValueError("chunk token limits must satisfy 0 < min <= target <= max")
        if not 0 <= self.overlap_tokens < self.max_tokens:
            raise ValueError("overlap_tokens must be between 0 and max_tokens")

    @classmethod
    def from_env(cls) -> "ChunkSettings":
        settings = cls(
            target_tokens=int(os.getenv("CHUNK_TARGET_TOKENS", "600")),
            max_tokens=int(os.getenv("CHUNK_MAX_TOKENS", "800")),
            min_tokens=int(os.getenv("CHUNK_MIN_TOKENS", "120")),
            overlap_tokens=int(os.getenv("CHUNK_OVERLAP_TOKENS", "80")),
            embed_review_required=_bool("EMBED_REVIEW_REQUIRED", False),
        )
        settings.validate()
        return settings


@dataclass(frozen=True)
class VectorSettings:
    siliconflow_api_key: str
    siliconflow_base_url: str
    embedding_model: str
    embedding_dimensions: int
    embedding_batch_size: int
    embedding_timeout_seconds: float
    embedding_max_retries: int
    query_instruction: str
    milvus_uri: str
    milvus_token: str | None
    milvus_database: str
    milvus_collection: str
    milvus_batch_size: int
    process_output_dir: Path

    @classmethod
    def from_env(cls) -> "VectorSettings":
        return cls(
            siliconflow_api_key=os.getenv("SILICONFLOW_API_KEY", ""),
            siliconflow_base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"),
            embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "1024")),
            embedding_batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "16")),
            embedding_timeout_seconds=float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "120")),
            embedding_max_retries=int(os.getenv("EMBEDDING_MAX_RETRIES", "3")),
            query_instruction=os.getenv(
                "QUERY_INSTRUCTION",
                "Given a user query, retrieve relevant document passages that answer it",
            ),
            milvus_uri=os.getenv("MILVUS_URI", "http://localhost:19530"),
            milvus_token=os.getenv("MILVUS_TOKEN") or None,
            milvus_database=os.getenv("MILVUS_DATABASE", "default"),
            milvus_collection=os.getenv("MILVUS_COLLECTION", "document_chunks"),
            milvus_batch_size=int(os.getenv("MILVUS_BATCH_SIZE", "100")),
            process_output_dir=Path(os.getenv("PROCESS_OUTPUT_DIR", "process-output")),
        )

    def require_external_services(self) -> None:
        if not self.siliconflow_api_key:
            raise ValueError("SILICONFLOW_API_KEY is required for vectorization")
        if self.embedding_dimensions <= 0:
            raise ValueError("EMBEDDING_DIMENSIONS must be positive")
        if self.embedding_model == "Qwen/Qwen3-Embedding-8B" and self.embedding_dimensions not in {
            64, 128, 256, 512, 768, 1024, 1536, 2048, 2560, 4096,
        }:
            raise ValueError("unsupported dimensions for Qwen/Qwen3-Embedding-8B")
        if self.embedding_batch_size <= 0 or self.milvus_batch_size <= 0:
            raise ValueError("batch sizes must be positive")
