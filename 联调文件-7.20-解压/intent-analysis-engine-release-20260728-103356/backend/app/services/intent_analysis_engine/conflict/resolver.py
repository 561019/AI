from __future__ import annotations

from collections import defaultdict

from app.schemas.intent_analysis import IntentAnalysisResult, TaskItem
from app.services.intent_analysis_engine.conflict.rules import conflict_missing_input
from app.services.intent_analysis_engine.conflict.schemas import ConflictDetectionResult, ConflictRecord


class ConflictResolver:
    """Applies resolution policy to tasks while keeping TaskList compatible."""

    def resolve(
        self,
        *,
        result: IntentAnalysisResult,
        detection: ConflictDetectionResult,
    ) -> IntentAnalysisResult:
        if not result.tasks or not detection.conflicts:
            return result

        conflicts_by_task: dict[str, list[ConflictRecord]] = defaultdict(list)
        fallback_task_id = result.tasks[0].task_id
        for conflict in detection.conflicts:
            task_id = conflict.task_id or fallback_task_id
            conflicts_by_task[task_id].append(conflict.model_copy(update={"task_id": task_id}))

        tasks = [
            self._apply_task_conflicts(task, conflicts_by_task.get(task.task_id, []))
            for task in result.tasks
        ]
        questions = list(result.clarification_questions)
        for task in tasks:
            for question in task.clarification_questions:
                if question not in questions:
                    questions.append(question)

        return result.model_copy(
            update={
                "tasks": tasks,
                "clarification_required": any(task.clarification_required for task in tasks)
                or result.clarification_required,
                "global_clarification_required": any(task.clarification_required for task in tasks)
                or result.global_clarification_required,
                "clarification_questions": questions,
            }
        )

    def _apply_task_conflicts(self, task: TaskItem, conflicts: list[ConflictRecord]) -> TaskItem:
        if not conflicts:
            return task

        existing_conflicts = [
            conflict
            if isinstance(conflict, ConflictRecord)
            else ConflictRecord.model_validate(conflict)
            for conflict in task.conflicts
        ]
        existing_ids = {conflict.conflict_id for conflict in existing_conflicts}
        merged_conflicts = [
            *existing_conflicts,
            *[conflict for conflict in conflicts if conflict.conflict_id not in existing_ids],
        ]
        blocking_conflicts = [
            conflict
            for conflict in merged_conflicts
            if conflict.resolution_status == "needs_clarification"
        ]
        missing_inputs = list(task.missing_inputs)
        questions = list(task.clarification_questions)
        for conflict in blocking_conflicts:
            missing = conflict_missing_input(conflict.conflict_type)
            if missing not in missing_inputs:
                missing_inputs.append(missing)
            if conflict.clarification_question and conflict.clarification_question not in questions:
                questions.append(conflict.clarification_question)

        return task.model_copy(
            update={
                "conflicts": [conflict.model_dump(mode="json") for conflict in merged_conflicts],
                "missing_inputs": missing_inputs,
                "clarification_required": bool(blocking_conflicts) or task.clarification_required,
                "clarification_questions": questions,
                "status": "needs_clarification" if blocking_conflicts else task.status,
                "blocked_reason": (
                    f"conflict:{blocking_conflicts[0].conflict_type}"
                    if blocking_conflicts
                    else task.blocked_reason
                ),
            }
        )
