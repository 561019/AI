from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    candidate_k: int = Field(default=30, ge=1, le=200)
    top_n: int = Field(default=5, ge=1, le=50)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    business_tags: list[str] = Field(min_length=1, max_length=50)
    include_review_required: bool = False
    min_vector_score: float | None = Field(default=None, ge=-1, le=1)
    min_rerank_score: float | None = None

    @model_validator(mode="after")
    def validate_limits(self) -> "SearchRequest":
        self.query = self.query.strip()
        if not self.query:
            raise ValueError("query cannot be blank")
        if self.top_n > self.candidate_k:
            raise ValueError("top_n cannot exceed candidate_k")
        self.document_ids = list(dict.fromkeys(value.strip() for value in self.document_ids if value.strip()))
        self.business_tags = list(dict.fromkeys(value.strip() for value in self.business_tags if value.strip()))
        if not self.business_tags:
            raise ValueError("at least one business tag is required")
        return self


class SearchHit(BaseModel):
    rank: int
    chunk_id: str
    document_id: str
    package_version: int
    chunk_index: int
    chunk_type: str
    text: str
    vector_score: float
    rerank_score: float
    needs_review: bool
    source_sha256: str
    business_tags: list[str]
    page_start: int | None = None
    page_end: int | None = None
    source_block_ids: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    asset_refs: list[str] = Field(default_factory=list)
    references: dict[str, str]


class SearchResponse(BaseModel):
    schema_version: str = Field(default="search-rerank/v1", serialization_alias="schema")
    request_id: str
    query: str
    embedding_model: str
    rerank_model: str
    collection: str
    candidate_count: int
    result_count: int
    elapsed_ms: dict[str, float]
    items: list[SearchHit]
