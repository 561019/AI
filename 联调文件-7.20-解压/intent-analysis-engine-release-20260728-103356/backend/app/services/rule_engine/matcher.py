import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models import FunctionRegistry, RuleMapping
from app.repositories.function_registry_repository import FunctionRegistryRepository
from app.schemas.rule_engine import RuleMatchResult
from app.services.rule_engine.repository import RuleEngineRepository

if TYPE_CHECKING:
    from app.services.intent_record_service import IntentRecordService


@dataclass(frozen=True)
class _RuleCandidate:
    rule: RuleMapping
    confidence: float


class RuleMatcher:
    """Level 1 matcher for explicit rule-based intent recognition."""

    def __init__(
        self,
        rule_repository: RuleEngineRepository,
        function_registry_repository: FunctionRegistryRepository,
        intent_record_service: "IntentRecordService | None" = None,
    ) -> None:
        self.rule_repository = rule_repository
        self.function_registry_repository = function_registry_repository
        self.intent_record_service = intent_record_service

    def match(
        self,
        text: str,
        *,
        user_id: str | None = None,
        conversation_id: str | None = None,
        record: bool = True,
    ) -> RuleMatchResult:
        started_at = time.perf_counter()
        normalized_text = self._normalize(text)
        if not normalized_text:
            return self._finalize_match(
                text=text,
                result=RuleMatchResult.unmatched(),
                started_at=started_at,
                user_id=user_id,
                conversation_id=conversation_id,
                record=record,
            )

        candidates: list[_RuleCandidate] = []
        for rule in self.rule_repository.list_active_rules():
            keyword_matched = self.keyword_match(normalized_text, rule.keyword)
            pattern_matched = self.pattern_match(normalized_text, rule.pattern)

            if not keyword_matched and not pattern_matched:
                continue

            confidence = self.calculate_confidence(
                normalized_text,
                keyword=rule.keyword,
                keyword_matched=keyword_matched,
                pattern_matched=pattern_matched,
            )
            candidates.append(_RuleCandidate(rule=rule, confidence=confidence))

        if not candidates:
            return self._finalize_match(
                text=text,
                result=RuleMatchResult.unmatched(),
                started_at=started_at,
                user_id=user_id,
                conversation_id=conversation_id,
                record=record,
            )

        candidates.sort(key=lambda candidate: (candidate.rule.priority, -candidate.confidence))

        for candidate in candidates:
            function = self.function_registry_repository.get_by_code(candidate.rule.function_code)
            if self._is_active_function(function):
                result = RuleMatchResult.matched_result(
                    function_code=function.function_code,
                    intent_category=function.intent_category,
                    target_engine=function.target_engine,
                    confidence=candidate.confidence,
                )
                return self._finalize_match(
                    text=text,
                    result=result,
                    started_at=started_at,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    record=record,
                )

        return self._finalize_match(
            text=text,
            result=RuleMatchResult.unmatched(),
            started_at=started_at,
            user_id=user_id,
            conversation_id=conversation_id,
            record=record,
        )

    def keyword_match(self, text: str, keyword: str) -> bool:
        normalized_text = self._normalize(text)
        normalized_keyword = self._normalize(keyword)
        return bool(normalized_keyword and normalized_keyword in normalized_text)

    def pattern_match(self, text: str, pattern: str | None) -> bool:
        if not pattern:
            return False

        try:
            return re.search(pattern, text, flags=re.IGNORECASE) is not None
        except re.error:
            return False

    def calculate_confidence(
        self,
        text: str,
        *,
        keyword: str,
        keyword_matched: bool,
        pattern_matched: bool,
    ) -> float:
        normalized_text = self._normalize(text)
        normalized_keyword = self._normalize(keyword)

        if keyword_matched and normalized_text == normalized_keyword:
            return 1.0

        if keyword_matched and pattern_matched:
            return 0.95

        if keyword_matched:
            return 0.9

        if pattern_matched:
            return 0.85

        return 0.0

    def _normalize(self, value: str | None) -> str:
        return (value or "").strip().lower()

    def _is_active_function(self, function: FunctionRegistry | None) -> bool:
        return function is not None and function.status == "active"

    def _finalize_match(
        self,
        *,
        text: str,
        result: RuleMatchResult,
        started_at: float,
        user_id: str | None,
        conversation_id: str | None,
        record: bool = True,
    ) -> RuleMatchResult:
        if record and self.intent_record_service is not None:
            self.intent_record_service.record_rule_match_result(
                request_text=text,
                user_id=user_id or "unknown",
                conversation_id=conversation_id or "unknown",
                match_result=result,
                cost_time=max(0, int((time.perf_counter() - started_at) * 1000)),
            )

        return result
