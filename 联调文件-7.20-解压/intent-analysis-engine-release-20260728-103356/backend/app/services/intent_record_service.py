from app.models import IntentRecord
from app.repositories.intent_record_repository import IntentRecordRepository
from app.schemas.rule_engine import RuleMatchResult


class IntentRecordError(Exception):
    """Base error for intent record service failures."""


class IntentRecordValidationError(IntentRecordError):
    """Raised when required record data is missing or invalid."""


class IntentRecordService:
    """Service for recording and querying intent analysis history."""

    def __init__(self, repository: IntentRecordRepository) -> None:
        self.repository = repository

    def record_intent_result(
        self,
        *,
        request_text: str,
        user_id: str,
        conversation_id: str,
        analysis_level: int | str,
        matched_function: str | None,
        confidence: float | None,
        result: str,
        cost_time: int | None = None,
    ) -> IntentRecord:
        self._validate_required("request_text", request_text)
        self._validate_required("user_id", user_id)
        self._validate_required("conversation_id", conversation_id)
        self._validate_required("analysis_level", str(analysis_level))
        self._validate_required("result", result)

        record = IntentRecord(
            request_text=request_text,
            user_id=user_id,
            conversation_id=conversation_id,
            analysis_level=str(analysis_level),
            matched_function=matched_function,
            confidence=confidence,
            result=result,
            cost_time=cost_time,
        )
        return self.repository.create_record(record)

    def record_rule_match_result(
        self,
        *,
        request_text: str,
        user_id: str,
        conversation_id: str,
        match_result: RuleMatchResult,
        cost_time: int | None = None,
    ) -> IntentRecord:
        return self.record_intent_result(
            request_text=request_text,
            user_id=user_id,
            conversation_id=conversation_id,
            analysis_level=match_result.level,
            matched_function=match_result.function_code,
            confidence=match_result.confidence,
            result="success" if match_result.matched else "unmatched",
            cost_time=cost_time,
        )

    def get_analysis_history(
        self,
        *,
        user_id: str | None = None,
        analysis_level: int | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IntentRecord]:
        if user_id is not None:
            return self.repository.query_by_user(user_id, limit=limit, offset=offset)

        if analysis_level is not None:
            return self.repository.query_by_level(analysis_level, limit=limit, offset=offset)

        return self.repository.list_records(limit=limit, offset=offset)

    def _validate_required(self, field_name: str, value: str) -> None:
        if not value or not value.strip():
            raise IntentRecordValidationError(f"{field_name} is required")
