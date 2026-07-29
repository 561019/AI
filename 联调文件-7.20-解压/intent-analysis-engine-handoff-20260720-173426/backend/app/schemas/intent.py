from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.schemas.common import ResultType, TaskList


class IntentAnalysisRequest(BaseModel):
    request_text: str = Field(min_length=1)
    real_user_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    tracking_id: str = Field(default_factory=lambda: str(uuid4()))


class IntentAnalysisResponse(BaseModel):
    tracking_id: str
    result_type: ResultType
    task_list: TaskList | None = None
    clarification_text: str | None = None
    explanation_text: str | None = None
    orchestration_receipt_id: str | None = None
