from typing import Literal

from pydantic import BaseModel, Field


class RuleMatchResult(BaseModel):
    level: Literal[1] = 1
    matched: bool
    function_code: str | None = None
    intent_category: str | None = None
    target_engine: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @classmethod
    def unmatched(cls) -> "RuleMatchResult":
        return cls(matched=False)

    @classmethod
    def matched_result(
        cls,
        *,
        function_code: str,
        intent_category: str,
        target_engine: str,
        confidence: float,
    ) -> "RuleMatchResult":
        return cls(
            matched=True,
            function_code=function_code,
            intent_category=intent_category,
            target_engine=target_engine,
            confidence=confidence,
        )
