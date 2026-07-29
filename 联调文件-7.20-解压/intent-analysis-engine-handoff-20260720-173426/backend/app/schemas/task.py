from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskItem(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    function_code: str
    function_name: str
    intent_category: str
    target_engine: str
    parameters: dict = Field(default_factory=dict)
    dependency: list[str] = Field(default_factory=list)
    priority: int = Field(default=1, ge=1)
    confidence: float = Field(ge=0, le=1)


class TaskList(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    tasks: list[TaskItem] = Field(default_factory=list)
    analysis_level: int = Field(ge=1, le=3)
    overall_confidence: float = Field(ge=0, le=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
