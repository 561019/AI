from pydantic import BaseModel, Field


class IntentAnalysisResult(BaseModel):
    level: int = Field(default=1, ge=1, le=3)
    matched: bool
    function_code: str | None = None
    intent_category: str | None = None
    target_engine: str | None = None
    confidence: float = Field(ge=0, le=1)
    record_id: str | None = None

    @classmethod
    def unmatched(cls, *, level: int = 1) -> "IntentAnalysisResult":
        return cls(level=level, matched=False, confidence=0)

    @classmethod
    def matched_result(
        cls,
        *,
        function_code: str,
        intent_category: str,
        target_engine: str,
        confidence: float,
        record_id: str | None,
        level: int = 1,
    ) -> "IntentAnalysisResult":
        return cls(
            level=level,
            matched=True,
            function_code=function_code,
            intent_category=intent_category,
            target_engine=target_engine,
            confidence=confidence,
            record_id=record_id,
        )
