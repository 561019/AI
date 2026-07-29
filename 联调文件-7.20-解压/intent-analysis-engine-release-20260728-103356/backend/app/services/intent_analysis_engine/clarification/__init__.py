from app.schemas.intent_analysis import IntentAnalysisResult, TaskItem
from app.services.intent_analysis_engine.clarification.answer_mapper import (
    AnswerMapping,
    ClarificationAnswerMapper,
)
from app.services.intent_analysis_engine.clarification.clarification_state import (
    ClarificationAnswerResult,
    ClarificationSession,
    ClarificationSessionStatus,
)
from app.services.intent_analysis_engine.clarification.session_manager import (
    ClarificationSessionManager,
    ClarificationSessionNotFound,
    get_default_clarification_session_manager,
)
from app.services.intent_analysis_engine.input_validator import QUESTION_BY_INPUT


class ClarificationService:
    """Backward-compatible global clarification aggregator."""

    def apply(self, result: IntentAnalysisResult) -> IntentAnalysisResult:
        missing_inputs = self._collect_missing_inputs(result.tasks)
        if not missing_inputs:
            return result

        questions = []
        for missing_input in missing_inputs:
            question = QUESTION_BY_INPUT.get(missing_input, f"请补充 {missing_input}。")
            if question not in questions:
                questions.append(question)

        return result.model_copy(
            update={
                "clarification_required": True,
                "global_clarification_required": True,
                "clarification_questions": questions,
            },
        )

    def _collect_missing_inputs(self, tasks: list[TaskItem]) -> list[str]:
        collected: list[str] = []
        for task in tasks:
            for missing_input in task.missing_inputs:
                if missing_input not in collected:
                    collected.append(missing_input)
        return collected


__all__ = [
    "AnswerMapping",
    "ClarificationAnswerMapper",
    "ClarificationAnswerResult",
    "ClarificationService",
    "ClarificationSession",
    "ClarificationSessionManager",
    "ClarificationSessionNotFound",
    "ClarificationSessionStatus",
    "get_default_clarification_session_manager",
]
