from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.intent_analysis import IntentAnalysisResult
from app.schemas.task import TaskList
from app.schemas.tasklist_confirmation import TaskListConfirmation


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ConversationHistoryItem(BaseModel):
    role: str = "user"
    text: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def accept_content_or_message(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"role": "user", "text": value}
        if isinstance(value, dict) and "text" not in value:
            return {
                **value,
                "text": value.get("content") or value.get("message"),
            }
        return value


class IntentAnalyzeRequest(BaseModel):
    text: str = Field(min_length=1)
    user_id: str = Field(default="anonymous", min_length=1)
    conversation_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    project_id: str | None = None
    history: list[ConversationHistoryItem] = Field(default_factory=list)
    debug: bool = False


class IntentAnalyzeResponse(BaseModel):
    success: bool
    data: IntentAnalysisResult | TaskList | None = None
    confirmation: TaskListConfirmation | None = None
    error: ApiError | None = None
    debug: dict[str, Any] | None = None


class ClarificationAnswerRequest(BaseModel):
    clarification_session_id: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class ClarificationAnswerResponse(BaseModel):
    task_id: str
    status: str
    missing_inputs: list[str] = Field(default_factory=list)
    final_inputs: dict[str, str] = Field(default_factory=dict)
    clarification_questions: list[str] = Field(default_factory=list)
    clarification_session_id: str
    session_status: str


class IntentRecordItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    request_text: str
    user_id: str
    conversation_id: str
    analysis_level: str
    matched_function: str | None = None
    confidence: float | None = None
    result: str
    cost_time: int | None = None
    created_at: datetime


class IntentHistoryData(BaseModel):
    records: list[IntentRecordItem]
    count: int
    limit: int
    offset: int


class IntentHistoryResponse(BaseModel):
    success: bool
    data: IntentHistoryData | None = None
    error: ApiError | None = None
