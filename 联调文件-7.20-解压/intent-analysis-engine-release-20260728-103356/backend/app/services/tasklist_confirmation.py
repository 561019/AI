from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from threading import RLock

from app.schemas.intent_analysis import IntentAnalysisResult, TaskItem
from app.schemas.tasklist_confirmation import (
    TaskListConfirmation,
    TaskListConfirmationCancelRequest,
    TaskListConfirmationConfirmRequest,
    TaskListConfirmationModifyRequest,
    TaskListConfirmationView,
)


class TaskListConfirmationSessionNotFound(KeyError):
    pass


class TaskListConfirmationVersionConflict(ValueError):
    pass


class TaskListConfirmationTransitionError(ValueError):
    pass


class TaskListConfirmationManager:
    """In-memory confirmation state kept outside the intent-analysis engine."""

    def __init__(self) -> None:
        self._sessions: dict[str, TaskListConfirmationView] = {}
        self._lock = RLock()

    def create_for_result(self, result: IntentAnalysisResult) -> TaskListConfirmation | None:
        if not result.tasks:
            return None

        confirmation = TaskListConfirmation(
            tasklist_version=self._tasklist_version(result),
            confirmation_status=self._status_for_tasklist(result),
        )
        view = TaskListConfirmationView(confirmation=confirmation, data=result)
        with self._lock:
            self._sessions[confirmation.confirmation_id] = view
        return confirmation

    def get(self, confirmation_id: str) -> TaskListConfirmationView:
        with self._lock:
            try:
                return self._sessions[confirmation_id]
            except KeyError as error:
                raise TaskListConfirmationSessionNotFound(confirmation_id) from error

    def confirm(
        self,
        *,
        confirmation_id: str,
        request: TaskListConfirmationConfirmRequest,
    ) -> TaskListConfirmationView:
        view = self.get(confirmation_id)
        self._validate_version(view.confirmation, request.tasklist_version)
        if view.confirmation.confirmation_status == "waiting_clarification":
            raise TaskListConfirmationTransitionError("Task list still requires clarification.")
        if view.confirmation.confirmation_status != "pending":
            raise TaskListConfirmationTransitionError("Task list is no longer pending confirmation.")

        now = self._now()
        confirmation = view.confirmation.model_copy(
            update={
                "confirmation_status": "confirmed",
                "confirmed_by": request.confirmed_by,
                "confirmed_at": now,
                "updated_at": now,
            }
        )
        return self._replace(confirmation_id, TaskListConfirmationView(confirmation=confirmation, data=view.data))

    def cancel(
        self,
        *,
        confirmation_id: str,
        request: TaskListConfirmationCancelRequest,
    ) -> TaskListConfirmationView:
        view = self.get(confirmation_id)
        self._validate_version(view.confirmation, request.tasklist_version)
        if view.confirmation.confirmation_status not in {"pending", "waiting_clarification"}:
            raise TaskListConfirmationTransitionError("Task list can no longer be cancelled.")

        now = self._now()
        confirmation = view.confirmation.model_copy(
            update={
                "confirmation_status": "cancelled",
                "cancelled_by": request.cancelled_by,
                "cancelled_at": now,
                "cancellation_reason": request.reason,
                "updated_at": now,
            }
        )
        return self._replace(confirmation_id, TaskListConfirmationView(confirmation=confirmation, data=view.data))

    def modify(
        self,
        *,
        confirmation_id: str,
        request: TaskListConfirmationModifyRequest,
    ) -> TaskListConfirmationView:
        view = self.get(confirmation_id)
        self._validate_version(view.confirmation, request.tasklist_version)
        if view.confirmation.confirmation_status not in {"pending", "waiting_clarification"}:
            raise TaskListConfirmationTransitionError("Task list can no longer be modified.")

        updated_tasklist = view.data.model_copy(
            update={
                "tasks": request.tasks,
                "clarification_required": any(task.clarification_required for task in request.tasks),
                "global_clarification_required": any(task.clarification_required for task in request.tasks),
                "clarification_questions": self._clarification_questions(request.tasks),
            }
        )
        now = self._now()
        confirmation = view.confirmation.model_copy(
            update={
                "tasklist_version": self._tasklist_version(updated_tasklist),
                "confirmation_status": self._status_for_tasklist(updated_tasklist),
                "modification_count": view.confirmation.modification_count + 1,
                "updated_at": now,
            }
        )
        return self._replace(
            confirmation_id,
            TaskListConfirmationView(confirmation=confirmation, data=updated_tasklist),
        )

    def update_task(self, task: TaskItem) -> None:
        """Synchronize a completed clarification into each pending task-list snapshot."""

        with self._lock:
            for confirmation_id, view in list(self._sessions.items()):
                if view.confirmation.confirmation_status not in {"pending", "waiting_clarification"}:
                    continue
                task_index = next(
                    (index for index, current in enumerate(view.data.tasks) if current.task_id == task.task_id),
                    None,
                )
                if task_index is None:
                    continue
                tasks = list(view.data.tasks)
                tasks[task_index] = task
                updated_tasklist = view.data.model_copy(
                    update={
                        "tasks": tasks,
                        "clarification_required": any(item.clarification_required for item in tasks),
                        "global_clarification_required": any(item.clarification_required for item in tasks),
                        "clarification_questions": self._clarification_questions(tasks),
                    }
                )
                confirmation = view.confirmation.model_copy(
                    update={
                        "tasklist_version": self._tasklist_version(updated_tasklist),
                        "confirmation_status": self._status_for_tasklist(updated_tasklist),
                        "updated_at": self._now(),
                    }
                )
                self._sessions[confirmation_id] = TaskListConfirmationView(
                    confirmation=confirmation,
                    data=updated_tasklist,
                )

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _replace(self, confirmation_id: str, view: TaskListConfirmationView) -> TaskListConfirmationView:
        with self._lock:
            self._sessions[confirmation_id] = view
        return view

    @staticmethod
    def _status_for_tasklist(result: IntentAnalysisResult) -> str:
        if result.clarification_required or any(task.clarification_required for task in result.tasks):
            return "waiting_clarification"
        return "pending"

    @staticmethod
    def _clarification_questions(tasks: list[TaskItem]) -> list[str]:
        return [question for task in tasks for question in task.clarification_questions]

    @staticmethod
    def _validate_version(confirmation: TaskListConfirmation, version: str) -> None:
        if confirmation.tasklist_version != version:
            raise TaskListConfirmationVersionConflict("Task list has changed. Refresh it before confirming.")

    @staticmethod
    def _tasklist_version(result: IntentAnalysisResult) -> str:
        payload = result.model_dump(
            mode="json",
            include={"tasks", "clarification_required", "global_clarification_required", "clarification_questions"},
        )
        serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)


_DEFAULT_MANAGER = TaskListConfirmationManager()


def get_default_tasklist_confirmation_manager() -> TaskListConfirmationManager:
    return _DEFAULT_MANAGER
