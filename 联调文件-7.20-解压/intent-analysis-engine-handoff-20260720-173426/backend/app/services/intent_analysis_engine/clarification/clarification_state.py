from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.schemas.intent_analysis import TaskItem


class ClarificationSessionStatus(str, Enum):
    WAITING_USER_INPUT = "WAITING_USER_INPUT"
    ANSWER_RECEIVED = "ANSWER_RECEIVED"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ClarificationSession(BaseModel):
    clarification_session_id: str = Field(default_factory=lambda: f"CS-{uuid4()}")
    task_id: str
    original_task: TaskItem
    missing_inputs: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    received_answers: dict[str, str] = Field(default_factory=dict)
    status: ClarificationSessionStatus = ClarificationSessionStatus.WAITING_USER_INPUT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self, *, status: ClarificationSessionStatus | None = None) -> "ClarificationSession":
        return self.model_copy(
            update={
                "status": status or self.status,
                "updated_at": datetime.now(timezone.utc),
            }
        )


class ClarificationAnswerResult(BaseModel):
    clarification_session_id: str
    task_id: str
    status: str
    session_status: ClarificationSessionStatus
    missing_inputs: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    final_inputs: dict[str, str] = Field(default_factory=dict)
    task: TaskItem
