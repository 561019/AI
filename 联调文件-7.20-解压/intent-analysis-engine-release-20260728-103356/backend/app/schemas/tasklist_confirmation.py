from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.schemas.intent_analysis import IntentAnalysisResult, TaskItem


TaskListConfirmationStatus = Literal[
    "waiting_clarification",
    "pending",
    "confirmed",
    "cancelled",
]


class TaskListConfirmation(BaseModel):
    """Confirmation state owned by the application layer, outside TaskList."""

    confirmation_id: str = Field(default_factory=lambda: str(uuid4()))
    tasklist_version: str
    confirmation_required: bool = True
    confirmation_status: TaskListConfirmationStatus
    modification_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    cancelled_by: str | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None


class TaskListConfirmationView(BaseModel):
    confirmation: TaskListConfirmation
    data: IntentAnalysisResult


class TaskListConfirmationConfirmRequest(BaseModel):
    tasklist_version: str = Field(min_length=1)
    confirmed_by: str = Field(default="anonymous", min_length=1)


class TaskListConfirmationCancelRequest(BaseModel):
    tasklist_version: str = Field(min_length=1)
    cancelled_by: str = Field(default="anonymous", min_length=1)
    reason: str | None = Field(default=None, max_length=1000)


class TaskListConfirmationModifyRequest(BaseModel):
    """A user-edited task list remains pending until it is confirmed again."""

    tasklist_version: str = Field(min_length=1)
    modified_by: str = Field(default="anonymous", min_length=1)
    tasks: list[TaskItem] = Field(min_length=1)
