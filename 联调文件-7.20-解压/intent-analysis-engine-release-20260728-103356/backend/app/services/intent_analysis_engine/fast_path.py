from app.schemas.intent_analysis import IntentAnalysisResult
from app.services.intent_analysis_engine.task_factory import TaskFactory


class QuestionFastPath:
    """Fast path for simple single-turn knowledge questions."""

    def __init__(self, task_factory: TaskFactory) -> None:
        self.task_factory = task_factory

    def match(self, text: str) -> IntentAnalysisResult | None:
        normalized = text.strip()
        if not normalized:
            return None

        if not self._is_question(normalized):
            return None

        task = self.task_factory.create_task(
            task_name="智能问答",
            task_type="QUESTION_ANSWER",
            required_inputs=[f"question:{normalized}"],
            missing_inputs=[],
            dependencies=[],
            execution_order=1,
            confidence=0.96,
        )
        return IntentAnalysisResult(
            original_text=normalized,
            intent_category="智能问答型",
            tasks=[task],
            clarification_required=False,
            clarification_questions=[],
            analysis_level=1,
            overall_confidence=0.96,
        )

    def _is_question(self, text: str) -> bool:
        question_mark = "?" in text or "？" in text
        question_phrase = any(phrase in text for phrase in ["是什么", "什么是", "如何", "怎么", "为什么"])
        knowledge_subject = any(subject in text for subject in ["政策", "制度", "规则", "标准", "定义", "说明", "报销"])
        return knowledge_subject and (question_mark or question_phrase)
