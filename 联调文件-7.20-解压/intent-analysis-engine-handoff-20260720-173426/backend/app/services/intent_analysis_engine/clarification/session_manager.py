from __future__ import annotations

from threading import RLock

from app.schemas.intent_analysis import IntentAnalysisResult, TaskItem
from app.services.intent_analysis_engine.clarification.answer_mapper import ClarificationAnswerMapper
from app.services.intent_analysis_engine.clarification.clarification_state import (
    ClarificationAnswerResult,
    ClarificationSession,
    ClarificationSessionStatus,
)
from app.services.intent_analysis_engine.input_validator import TaskInputValidator


class ClarificationSessionNotFound(KeyError):
    pass


class ClarificationSessionManager:
    """In-memory clarification session store for task-level recovery."""

    def __init__(
        self,
        *,
        answer_mapper: ClarificationAnswerMapper | None = None,
    ) -> None:
        self.answer_mapper = answer_mapper or ClarificationAnswerMapper()
        self._sessions: dict[str, ClarificationSession] = {}
        self._lock = RLock()

    def create_sessions_for_result(self, result: IntentAnalysisResult) -> IntentAnalysisResult:
        updated_tasks: list[TaskItem] = []
        for task in result.tasks:
            if task.clarification_required and task.missing_inputs:
                session = self.create_session(task)
                updated_tasks.append(
                    task.model_copy(
                        update={"clarification_session_id": session.clarification_session_id}
                    )
                )
            else:
                updated_tasks.append(task)
        return result.model_copy(update={"tasks": updated_tasks})

    def create_session(self, task: TaskItem) -> ClarificationSession:
        session = ClarificationSession(
            task_id=task.task_id,
            original_task=task,
            missing_inputs=list(task.missing_inputs),
            questions=list(task.clarification_questions),
        )
        with self._lock:
            self._sessions[session.clarification_session_id] = session
        return session

    def get_session(self, clarification_session_id: str) -> ClarificationSession:
        with self._lock:
            try:
                return self._sessions[clarification_session_id]
            except KeyError as error:
                raise ClarificationSessionNotFound(clarification_session_id) from error

    def answer(
        self,
        *,
        clarification_session_id: str,
        answer: str,
        validator: TaskInputValidator,
    ) -> ClarificationAnswerResult:
        session = self.get_session(clarification_session_id).touch(
            status=ClarificationSessionStatus.ANSWER_RECEIVED,
        )
        with self._lock:
            self._sessions[clarification_session_id] = session

        mapping = self.answer_mapper.map_answer(
            answer=answer,
            missing_inputs=session.missing_inputs,
        )
        validating_session = session.model_copy(
            update={
                "received_answers": {
                    **session.received_answers,
                    **mapping.mapped_inputs,
                },
                "status": ClarificationSessionStatus.VALIDATING,
            }
        ).touch()
        with self._lock:
            self._sessions[clarification_session_id] = validating_session

        updated_task = self._apply_inputs(
            task=validating_session.original_task,
            required_inputs=mapping.required_inputs,
            clarification_session_id=clarification_session_id,
        )
        validated_task = validator.validate_task_list([updated_task])[0]
        final_status = (
            ClarificationSessionStatus.COMPLETED
            if validated_task.status == "ready"
            else ClarificationSessionStatus.WAITING_USER_INPUT
        )
        updated_session = validating_session.model_copy(
            update={
                "original_task": validated_task,
                "missing_inputs": list(validated_task.missing_inputs),
                "questions": list(validated_task.clarification_questions),
                "status": final_status,
            }
        ).touch()
        with self._lock:
            self._sessions[clarification_session_id] = updated_session

        return ClarificationAnswerResult(
            clarification_session_id=clarification_session_id,
            task_id=validated_task.task_id,
            status=validated_task.status,
            session_status=updated_session.status,
            missing_inputs=validated_task.missing_inputs,
            clarification_questions=validated_task.clarification_questions,
            final_inputs={
                **self._final_inputs_from_task(validated_task),
                **mapping.final_inputs,
            },
            task=validated_task,
        )

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _apply_inputs(
        self,
        *,
        task: TaskItem,
        required_inputs: list[str],
        clarification_session_id: str,
    ) -> TaskItem:
        existing = list(task.required_inputs)
        existing_keys = {value.split(":", 1)[0] for value in existing}
        additions = [
            value
            for value in required_inputs
            if value.split(":", 1)[0] not in existing_keys
        ]
        return task.model_copy(
            update={
                "required_inputs": [*existing, *additions],
                "clarification_session_id": clarification_session_id,
            }
        )

    def _final_inputs_from_task(self, task: TaskItem) -> dict[str, str]:
        final_inputs: dict[str, str] = {}
        for value in task.required_inputs:
            if ":" not in value:
                continue
            key, raw_value = value.split(":", 1)
            if key == "sales_data_source":
                key = "data_source"
            elif key == "statistical_range" and "区域" in raw_value:
                key = "data_scope"
            final_inputs.setdefault(key, raw_value)
        return final_inputs


_DEFAULT_MANAGER = ClarificationSessionManager()


def get_default_clarification_session_manager() -> ClarificationSessionManager:
    return _DEFAULT_MANAGER
