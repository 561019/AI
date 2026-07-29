from enum import StrEnum

from pydantic import BaseModel, Field


class ResultType(StrEnum):
    HANDOFF = "handoff"
    CLARIFICATION = "clarification"
    SAFEGUARD = "safeguard"


class JudgmentLevel(StrEnum):
    RULE = "rule"
    SEMANTIC = "semantic"
    MODEL = "model"
    NOT_STARTED = "not_started"


class TaskItem(BaseModel):
    sequence: int = Field(ge=1)
    function_code: str
    execution_engine: str
    key_information: dict = Field(default_factory=dict)


class TaskDependency(BaseModel):
    before_sequence: int = Field(ge=1)
    after_sequence: int = Field(ge=1)


class TaskList(BaseModel):
    request_id: str
    requester_real_user_id: str
    conversation_id: str
    item_count: int = Field(ge=0)
    items: list[TaskItem] = Field(default_factory=list)
    dependencies: list[TaskDependency] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    judgment_level: JudgmentLevel
    source_text: str
    context_summary: str | None = None
