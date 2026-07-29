from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


ConflictType = Literal[
    "DATA_SOURCE_CONFLICT",
    "TIME_RANGE_CONFLICT",
    "STATISTICAL_DEFINITION_CONFLICT",
    "CURRENT_CONTEXT_CONFLICT",
    "PROJECT_USER_CONTEXT_CONFLICT",
]

ConflictSeverity = Literal["info", "warning", "blocking"]
ConflictSource = Literal[
    "current_input",
    "conversation_context",
    "project_context",
    "historical_projects",
]
ResolutionStatus = Literal["resolved", "needs_clarification", "recorded"]


class ContextSignal(BaseModel):
    field: str
    value: str
    source: ConflictSource
    raw_text: str = ""
    explicit: bool = False


class ConflictRecord(BaseModel):
    conflict_id: str = Field(default_factory=lambda: f"CF-{uuid4()}")
    task_id: str = ""
    conflict_type: ConflictType
    severity: ConflictSeverity
    description: str
    left_value: str
    right_value: str
    source_left: ConflictSource
    source_right: ConflictSource
    resolution_status: ResolutionStatus
    clarification_question: str | None = None


class ConflictDetectionResult(BaseModel):
    conflicts: list[ConflictRecord] = Field(default_factory=list)

    @property
    def has_blocking_conflict(self) -> bool:
        return any(conflict.resolution_status == "needs_clarification" for conflict in self.conflicts)
