import time

from app.schemas.intent_result import IntentAnalysisResult
from app.schemas.task import TaskList
from app.services.function_registry_service import FunctionRegistryService
from app.services.intent_record_service import IntentRecordService
from app.services.rule_engine import RuleMatcher
from app.services.task_builder import TaskListBuilder


class Level1IntentAnalyzer:
    """Internal orchestration for Level 1 intent analysis."""

    def __init__(
        self,
        *,
        rule_matcher: RuleMatcher,
        function_registry_service: FunctionRegistryService,
        intent_record_service: IntentRecordService,
        task_list_builder: TaskListBuilder | None = None,
    ) -> None:
        self.rule_matcher = rule_matcher
        self.function_registry_service = function_registry_service
        self.intent_record_service = intent_record_service
        self.task_list_builder = task_list_builder or TaskListBuilder()

    def analyze(
        self,
        *,
        text: str,
        user_id: str,
        conversation_id: str,
        record: bool = True,
    ) -> TaskList:
        started_at = time.perf_counter()
        match_result = self.rule_matcher.match(text, record=False)
        cost_time = max(0, int((time.perf_counter() - started_at) * 1000))

        if not match_result.matched:
            record_id = None
            if record:
                intent_record = self.intent_record_service.record_intent_result(
                    request_text=text,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    analysis_level=1,
                    matched_function=None,
                    confidence=0,
                    result="unmatched",
                    cost_time=cost_time,
                )
                record_id = intent_record.id
            return self.task_list_builder.build_from_intent_result(
                intent_result=IntentAnalysisResult.unmatched(),
                user_id=user_id,
                request_id=record_id,
            )

        function = self.function_registry_service.validate_function_status(
            match_result.function_code,
        )
        record_id = None
        if record:
            intent_record = self.intent_record_service.record_intent_result(
                request_text=text,
                user_id=user_id,
                conversation_id=conversation_id,
                analysis_level=1,
                matched_function=function.function_code,
                confidence=match_result.confidence,
                result="success",
                cost_time=cost_time,
            )
            record_id = intent_record.id

        intent_result = IntentAnalysisResult.matched_result(
            function_code=function.function_code,
            intent_category=function.intent_category,
            target_engine=function.target_engine,
            confidence=match_result.confidence or 0,
            record_id=record_id,
        )
        return self.task_list_builder.build_from_intent_result(
            intent_result=intent_result,
            user_id=user_id,
            request_id=record_id,
            function_name=function.function_name,
        )
