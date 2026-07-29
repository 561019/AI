from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    """Normalized response returned by every LLM provider."""

    provider: str
    model: str
    content: str
    parsed_json: dict[str, Any] = Field(default_factory=dict)
    raw_response: dict[str, Any] | None = None
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    elapsed_ms: int = 0
    retry_count: int = 0
    fallback_used: bool = False
    fallback_provider: str | None = None
    error: str | None = None
    debug: dict[str, Any] = Field(default_factory=dict)
