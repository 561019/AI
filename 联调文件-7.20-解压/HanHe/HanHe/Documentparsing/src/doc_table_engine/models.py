from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ParseRoute(StrEnum):
    DIRECT = "direct"
    OCR = "ocr"
    TEMPLATE = "template"


class ParseStatus(StrEnum):
    COMPLETED = "completed"
    REVIEW_REQUIRED = "review_required"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SourceRef:
    file_sha256: str
    file_name: str
    sheet: str | None = None
    cell: str | None = None
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    table: int | None = None
    row: int | None = None
    column: int | None = None
    paragraph: int | None = None


@dataclass
class ParsedValue:
    raw_value: Any
    source: SourceRef
    value_id: str = ""
    value_type: str = "text"
    confidence: float = 1.0
    confidence_basis: str = "未标注"
    needs_review: bool = False
    auto_fill_allowed: bool = True
    field_name: str | None = None
    target_field: str | None = None


@dataclass
class ParsedTable:
    name: str
    values: list[ParsedValue] = field(default_factory=list)


@dataclass
class ParsedContent:
    text_blocks: list[ParsedValue] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    fields: list[ParsedValue] = field(default_factory=list)
    ai_structured: dict[str, Any] | None = None


@dataclass
class OriginalRecord:
    file_name: str
    media_type: str
    size_bytes: int
    sha256: str
    stored_path: str | None = None


@dataclass
class RegistrationRecord:
    job_id: str
    actor_id: str
    business_tags: list[str]
    route: ParseRoute
    status: ParseStatus
    created_at: str
    template_id: str | None = None
    template_version: str | None = None
    review_count: int = 0
    review_value_ids: list[str] = field(default_factory=list)


@dataclass
class ParseResult:
    original: OriginalRecord
    registration: RegistrationRecord
    semantic: ParsedContent

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
