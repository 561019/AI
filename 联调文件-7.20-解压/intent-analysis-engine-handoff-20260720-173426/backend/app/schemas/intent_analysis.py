from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator


TaskStatus = Literal["ready", "needs_clarification", "waiting_dependency"]


class TaskItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    task_type: str
    task_description: str = ""
    action: str = ""
    object: str = ""
    required_inputs: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    clarification_session_id: str | None = None
    clarification_required: bool = False
    clarification_questions: list[str] = Field(default_factory=list)
    status: TaskStatus = "ready"
    blocked_reason: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_task_fields(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        description = (
            normalized.get("task_description")
            or normalized.get("task_name")
            or normalized.get("function_name")
            or normalized.get("task_type")
            or ""
        )
        normalized["task_description"] = str(description)
        action, business_object = cls._derive_action_object(str(description))
        normalized["action"] = str(normalized.get("action") or action)
        normalized["object"] = str(normalized.get("object") or normalized.get("business_object") or business_object)
        return normalized

    @property
    def task_name(self) -> str:
        return self.task_description

    @staticmethod
    def _derive_action_object(description: str) -> tuple[str, str]:
        text = description.strip()
        if not text:
            return "", ""
        special_prefixes = (
            ("同比分析", "分析"),
            ("环比分析", "分析"),
            ("问题分析", "分析"),
            ("预测分析", "预测"),
        )
        for prefix, action in special_prefixes:
            if text.startswith(prefix):
                return action, text[len(prefix) :].strip() or text
        action_terms = (
            "整理",
            "分析",
            "生成",
            "计算",
            "查询",
            "获取",
            "解析",
            "提取",
            "读取",
            "筛选",
            "排序",
            "汇总",
            "统计",
            "预测",
            "办理",
            "发起",
            "创建",
            "转换",
            "导出",
            "同步",
            "监控",
        )
        matches = [
            (text.find(action), order, action)
            for order, action in enumerate(action_terms)
            if text.find(action) >= 0
        ]
        if matches:
            index, _, action = min(matches)
            return action, text[index + len(action) :].strip() or text[:index].strip() or text
        return "", text


class IntentAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    _llm_evidence_spans: list[str] = PrivateAttr(default_factory=list)

    request_id: str = Field(default_factory=lambda: str(uuid4()), exclude=True)
    original_text: str = Field(default="", exclude=True)
    intent_category: str = Field(default="", exclude=True)
    tasks: list[TaskItem] = Field(default_factory=list)
    clarification_required: bool = False
    global_clarification_required: bool = False
    clarification_questions: list[str] = Field(default_factory=list)
    analysis_level: int = Field(default=1, ge=1, le=3, exclude=True)
    overall_confidence: float = Field(default=0, ge=0, le=1, exclude=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), exclude=True)

    @model_validator(mode="after")
    def sync_global_clarification(self) -> "IntentAnalysisResult":
        global_required = bool(
            self.global_clarification_required
            or self.clarification_required
            or any(task.clarification_required for task in self.tasks)
        )
        self.global_clarification_required = global_required
        self.clarification_required = global_required
        return self

    @classmethod
    def model_json_schema(cls, *args: object, **kwargs: object) -> dict:
        return {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "string"},
                            "task_type": {"type": "string"},
                            "task_description": {"type": "string"},
                            "action": {"type": "string"},
                            "object": {"type": "string"},
                            "required_inputs": {"type": "array", "items": {"type": "string"}},
                            "missing_inputs": {"type": "array", "items": {"type": "string"}},
                            "clarification_session_id": {"type": ["string", "null"]},
                            "clarification_required": {"type": "boolean"},
                            "clarification_questions": {"type": "array", "items": {"type": "string"}},
                            "status": {
                                "type": "string",
                                "enum": ["ready", "needs_clarification", "waiting_dependency"],
                            },
                            "blocked_reason": {"type": ["string", "null"]},
                            "dependencies": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": [
                            "task_type",
                            "task_description",
                            "action",
                            "object",
                            "required_inputs",
                            "missing_inputs",
                            "clarification_required",
                            "clarification_questions",
                            "status",
                            "dependencies",
                            "confidence",
                        ],
                    },
                },
                "clarification_required": {"type": "boolean"},
                "global_clarification_required": {"type": "boolean"},
                "clarification_questions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["tasks", "clarification_required", "clarification_questions"],
        }
