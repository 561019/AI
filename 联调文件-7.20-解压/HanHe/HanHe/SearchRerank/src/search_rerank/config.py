from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    siliconflow_api_key: str
    siliconflow_base_url: str
    embedding_model: str
    embedding_dimensions: int
    embedding_timeout_seconds: float
    embedding_max_retries: int
    query_instruction: str
    rerank_model: str
    rerank_instruction: str
    rerank_timeout_seconds: float
    rerank_max_retries: int
    milvus_uri: str
    milvus_token: str | None
    milvus_database: str
    milvus_collection: str
    default_candidate_k: int
    default_top_n: int
    max_candidate_k: int
    permission_api_url: str | None
    permission_api_key: str | None
    allow_demo_actor: bool

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            siliconflow_api_key=os.getenv("SILICONFLOW_API_KEY", ""),
            siliconflow_base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"),
            embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "1024")),
            embedding_timeout_seconds=float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "120")),
            embedding_max_retries=int(os.getenv("EMBEDDING_MAX_RETRIES", "3")),
            query_instruction=os.getenv(
                "QUERY_INSTRUCTION",
                "Given a user query, retrieve relevant document passages that answer it",
            ),
            rerank_model=os.getenv("RERANK_MODEL", "Qwen/Qwen3-Reranker-8B"),
            rerank_instruction=os.getenv(
                "RERANK_INSTRUCTION",
                "根据用户查询，按照文档片段对回答查询的相关性进行排序",
            ),
            rerank_timeout_seconds=float(os.getenv("RERANK_TIMEOUT_SECONDS", "120")),
            rerank_max_retries=int(os.getenv("RERANK_MAX_RETRIES", "3")),
            milvus_uri=os.getenv("MILVUS_URI", "http://localhost:19530"),
            milvus_token=os.getenv("MILVUS_TOKEN") or None,
            milvus_database=os.getenv("MILVUS_DATABASE", "default"),
            milvus_collection=os.getenv("MILVUS_COLLECTION", "hanhe_document_chunks"),
            default_candidate_k=int(os.getenv("DEFAULT_CANDIDATE_K", "30")),
            default_top_n=int(os.getenv("DEFAULT_TOP_N", "5")),
            max_candidate_k=int(os.getenv("MAX_CANDIDATE_K", "200")),
            permission_api_url=os.getenv("PERMISSION_API_URL") or None,
            permission_api_key=os.getenv("PERMISSION_API_KEY") or None,
            allow_demo_actor=_bool("ALLOW_DEMO_ACTOR", True),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.siliconflow_api_key:
            raise ValueError("SILICONFLOW_API_KEY is required")
        if self.embedding_dimensions <= 0:
            raise ValueError("EMBEDDING_DIMENSIONS must be positive")
        if not 0 < self.default_top_n <= self.default_candidate_k <= self.max_candidate_k:
            raise ValueError("search limits must satisfy 0 < top_n <= candidate_k <= max_candidate_k")
        if self.embedding_timeout_seconds <= 0 or self.rerank_timeout_seconds <= 0:
            raise ValueError("model timeouts must be positive")

