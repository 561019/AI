from __future__ import annotations

from pydantic import BaseModel, Field


class TaskCreateRequest(BaseModel):
    actor_id: str = Field(..., description="当前操作真人")
    scenario_id: str = Field(..., description="演示场景")
    requirement: str | None = Field(None, description="L4 原始请求")


class IntegrationSubtaskRequest(BaseModel):
    trace_id: str | None = None
    message_id: str | None = None
    parent_message_id: str | None = None
    workflow_instance_id: str | None = None
    node_id: str | None = None
    task_id: str | None = None
    idempotency_key: str | None = None
    caller: dict = Field(default_factory=dict)
    actor: dict = Field(default_factory=dict)
    capability: dict = Field(default_factory=dict)
    request_type: str = "execute"
    input: dict = Field(default_factory=dict)
    expected_return: dict = Field(default_factory=dict)
    policy: dict = Field(default_factory=dict)
    callback_url: str | None = None
    callback_envelope_url: str | None = None
    callback_protocol: str | None = None
    callback_timeout_seconds: int | None = None
    callback_headers: dict = Field(default_factory=dict)
    parent_task_id: str | None = None
    caller_engine: str = "流程执行引擎"
    operator_real_person_id: str | None = None
    requested_service: str | None = None
    content_type: str | None = None
    input_brief: str | None = None
    source_material_refs: list[str] = Field(default_factory=list)
    template_id: str | None = None
    expected_output: str | None = None
    review_policy: str = "pending_human_confirmation"
    security_context: dict = Field(default_factory=dict)
    scenario_id: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    knowledge_refs: list[str] = Field(default_factory=list)
    context_refs: list[str] = Field(default_factory=list)
    decision_id: str | None = None
    audit_ref: str | None = None


class ReviewResultRequest(BaseModel):
    approver_id: str
    decision: str = Field(..., pattern="^(approve|reject)$")
    reason: str | None = None


class FreezeRequest(BaseModel):
    actor_id: str
    reason: str = "审计冻结。"
