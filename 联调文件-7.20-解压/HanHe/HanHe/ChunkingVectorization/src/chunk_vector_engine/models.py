from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class StandardBlock:
    block_id: str
    block_type: str
    order: int
    text: str
    page: int | None
    bbox: list[float] | tuple[float, ...] | None
    confidence: float
    needs_review: bool
    heading_path: list[str]
    source_ref: dict[str, Any]
    asset_ref: str | None = None
    parquet_ref: str | None = None
    field_name: str | None = None
    target_field: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    package_version: int
    chunk_index: int
    chunk_type: str
    text: str
    embedding_text: str
    token_count: int
    source_block_ids: list[str]
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    source_refs: list[dict[str, Any]]
    asset_refs: list[str]
    confidence: float
    needs_review: bool
    eligible_for_embedding: bool
    business_tags: list[str]
    source_sha256: str
    strategy_version: str
    table_row_start: int | None = None
    table_row_end: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "document-chunk/v1", **asdict(self)}

