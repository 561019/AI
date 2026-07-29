from typing import Literal

from pydantic import BaseModel, Field


class SemanticCandidate(BaseModel):
    function_code: str
    function_name: str | None = None
    intent_category: str | None = None
    target_engine: str | None = None
    engine_code: str | None = None
    task_type: str | None = None
    task_name: str | None = None
    intent_description: str | None = None
    examples: list[str] | None = None
    confidence: float = Field(ge=0, le=1)
    similarity_score: float = Field(ge=0, le=1)


class SemanticResult(BaseModel):
    level: Literal[2] = 2
    matched: bool
    candidates: list[SemanticCandidate] = Field(default_factory=list)
    function_code: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    similarity_score: float = Field(default=0, ge=0, le=1)

    @classmethod
    def unmatched(cls, candidates: list[SemanticCandidate] | None = None) -> "SemanticResult":
        return cls(matched=False, candidates=candidates or [])

    @classmethod
    def matched_result(
        cls,
        *,
        candidates: list[SemanticCandidate],
    ) -> "SemanticResult":
        top_candidate = candidates[0]
        return cls(
            matched=True,
            candidates=candidates,
            function_code=top_candidate.function_code,
            confidence=top_candidate.confidence,
            similarity_score=top_candidate.similarity_score,
        )
