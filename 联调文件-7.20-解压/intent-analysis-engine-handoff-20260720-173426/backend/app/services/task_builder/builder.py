from app.schemas.intent_result import IntentAnalysisResult
from app.schemas.task import TaskItem, TaskList


class TaskListBuilder:
    """Builds the unified task list output for intent analysis results."""

    def build_from_intent_result(
        self,
        *,
        intent_result: IntentAnalysisResult,
        user_id: str,
        request_id: str | None = None,
        function_name: str | None = None,
        parameters: dict | None = None,
        dependency: list[str] | None = None,
        priority: int = 1,
        additional_tasks: list[TaskItem] | None = None,
    ) -> TaskList:
        tasks: list[TaskItem] = []

        if intent_result.matched:
            tasks.append(
                TaskItem(
                    function_code=intent_result.function_code,
                    function_name=function_name or intent_result.function_code or "",
                    intent_category=intent_result.intent_category,
                    target_engine=intent_result.target_engine,
                    parameters=parameters or {},
                    dependency=dependency or [],
                    priority=priority,
                    confidence=intent_result.confidence,
                ),
            )

        if additional_tasks:
            tasks.extend(additional_tasks)

        task_list_data = {
            "user_id": user_id,
            "tasks": tasks,
            "analysis_level": intent_result.level,
            "overall_confidence": self._calculate_overall_confidence(tasks, intent_result.confidence),
        }
        resolved_request_id = request_id or intent_result.record_id
        if resolved_request_id is not None:
            task_list_data["request_id"] = resolved_request_id

        return TaskList(**task_list_data)

    def _calculate_overall_confidence(
        self,
        tasks: list[TaskItem],
        fallback_confidence: float,
    ) -> float:
        if not tasks:
            return 0

        return min(task.confidence for task in tasks) if len(tasks) > 1 else fallback_confidence
