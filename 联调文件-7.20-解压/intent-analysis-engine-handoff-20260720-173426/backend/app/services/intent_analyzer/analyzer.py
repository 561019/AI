from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.schemas.intent_result import IntentAnalysisResult
from app.schemas.llm import NeedConfirmationResult
from app.schemas.semantic import SemanticResult
from app.schemas.task import TaskList
from app.services.intent_analyzer.level1_analyzer import Level1IntentAnalyzer
from app.services.intent_record_service import IntentRecordService
from app.services.llm_engine import LLMIntentAnalyzer
from app.services.semantic_engine import SemanticMatcher
from app.services.task_builder import TaskListBuilder


@dataclass(frozen=True)
class IntentAnalysisWithDebug:
    result: TaskList | NeedConfirmationResult
    debug: dict[str, Any]


class IntentAnalyzer:
    """Unified intent analysis entry for Level 1, Level 2, and Level 3."""

    def __init__(
        self,
        *,
        level1_analyzer: Level1IntentAnalyzer,
        semantic_matcher: SemanticMatcher,
        llm_analyzer: LLMIntentAnalyzer,
        intent_record_service: IntentRecordService,
        task_list_builder: TaskListBuilder | None = None,
        rule_threshold: float | None = None,
        semantic_threshold: float | None = None,
    ) -> None:
        self.level1_analyzer = level1_analyzer
        self.semantic_matcher = semantic_matcher
        self.llm_analyzer = llm_analyzer
        self.intent_record_service = intent_record_service
        self.task_list_builder = task_list_builder or TaskListBuilder()
        self.rule_threshold = settings.rule_threshold if rule_threshold is None else rule_threshold
        self.semantic_threshold = settings.semantic_threshold if semantic_threshold is None else semantic_threshold

    def analyze(
        self,
        *,
        text: str,
        user_id: str,
        conversation_id: str,
    ) -> TaskList | NeedConfirmationResult:
        return self.analyze_with_debug(
            text=text,
            user_id=user_id,
            conversation_id=conversation_id,
        ).result

    def analyze_with_debug(
        self,
        *,
        text: str,
        user_id: str,
        conversation_id: str,
    ) -> IntentAnalysisWithDebug:
        debug: dict[str, Any] = {
            "level1_result": None,
            "level2_result": None,
            "level3_result": None,
            "final_tasklist": None,
        }

        level1_task_list = self.level1_analyzer.analyze(
            text=text,
            user_id=user_id,
            conversation_id=conversation_id,
            record=False,
        )
        debug["level1_result"] = self._dump_model(level1_task_list)
        if self._is_confident_task_list(level1_task_list, self.rule_threshold):
            final_task_list = self._record_final_task_list(
                task_list=level1_task_list,
                text=text,
                user_id=user_id,
                conversation_id=conversation_id,
                analysis_level=1,
            )
            debug["final_tasklist"] = self._dump_model(final_task_list)
            return IntentAnalysisWithDebug(result=final_task_list, debug=debug)

        semantic_result = self.semantic_matcher.analyze(text)
        debug["level2_result"] = self._dump_model(semantic_result)
        if (
            semantic_result.matched
            and semantic_result.candidates
            and semantic_result.confidence >= self.semantic_threshold
        ):
            semantic_task_list = self._semantic_result_to_task_list(
                semantic_result=semantic_result,
                user_id=user_id,
            )
            final_task_list = self._record_final_task_list(
                task_list=semantic_task_list,
                text=text,
                user_id=user_id,
                conversation_id=conversation_id,
                analysis_level=2,
            )
            debug["final_tasklist"] = self._dump_model(final_task_list)
            return IntentAnalysisWithDebug(result=final_task_list, debug=debug)

        llm_result = self.llm_analyzer.analyze(text, user_id=user_id)
        debug["level3_result"] = self._dump_model(llm_result)
        if isinstance(llm_result, NeedConfirmationResult):
            self.intent_record_service.record_intent_result(
                request_text=text,
                user_id=user_id,
                conversation_id=conversation_id,
                analysis_level=3,
                matched_function=None,
                confidence=0,
                result="need_confirmation",
            )
            return IntentAnalysisWithDebug(result=llm_result, debug=debug)

        final_task_list = self._record_final_task_list(
            task_list=llm_result,
            text=text,
            user_id=user_id,
            conversation_id=conversation_id,
            analysis_level=3,
        )
        debug["final_tasklist"] = self._dump_model(final_task_list)
        return IntentAnalysisWithDebug(result=final_task_list, debug=debug)

    def _semantic_result_to_task_list(
        self,
        *,
        semantic_result: SemanticResult,
        user_id: str,
    ) -> TaskList:
        top_candidate = semantic_result.candidates[0]
        intent_result = IntentAnalysisResult.matched_result(
            function_code=top_candidate.function_code,
            intent_category=top_candidate.intent_category or "",
            target_engine=top_candidate.target_engine or "",
            confidence=semantic_result.confidence,
            record_id=None,
            level=2,
        )
        return self.task_list_builder.build_from_intent_result(
            intent_result=intent_result,
            user_id=user_id,
            function_name=top_candidate.function_name,
        )

    def _record_final_task_list(
        self,
        *,
        task_list: TaskList,
        text: str,
        user_id: str,
        conversation_id: str,
        analysis_level: int,
    ) -> TaskList:
        first_task = task_list.tasks[0] if task_list.tasks else None
        record = self.intent_record_service.record_intent_result(
            request_text=text,
            user_id=user_id,
            conversation_id=conversation_id,
            analysis_level=analysis_level,
            matched_function=first_task.function_code if first_task else None,
            confidence=task_list.overall_confidence,
            result="success" if first_task else "unmatched",
        )
        return task_list.model_copy(
            update={
                "request_id": record.id,
                "analysis_level": analysis_level,
            },
        )

    def _is_confident_task_list(self, task_list: TaskList, threshold: float) -> bool:
        return bool(task_list.tasks) and task_list.overall_confidence >= threshold

    def _dump_model(self, value: TaskList | SemanticResult | NeedConfirmationResult) -> dict[str, Any]:
        return value.model_dump(mode="json")
