from __future__ import annotations

from pydantic import BaseModel, Field


class IntegrationRunRequest(BaseModel):
    trace_id: str | None = Field(None, description="跨模块链路追踪编号")
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
    actor_id: str = Field("U001", description="当前操作真人")
    task_type: str = Field("multimedia_poster", description="知识库取材任务类型")
    capability_id: str = Field("text_to_image", description="多媒体能力接口位")
    output_type: str = Field("poster_plan", description="本次 LLM 产出类型")
    requirement: str = Field(..., description="L4 原始任务描述")
    top_k: int = Field(10, ge=1, le=20)
    use_llm: bool = Field(True, description="是否真实调用 LLM；关闭时只返回 prompt")
    source_engine: str | None = Field(None, description="上游派发来源编码")
    source_engine_name: str | None = Field(None, description="上游派发来源名称")
    parent_flow_id: str | None = Field(None, description="流程执行引擎实例编号")
    upstream_content_task_id: str | None = Field(None, description="上游内容产出任务编号")
    upstream_content_summary: str | None = Field(None, description="上游内容产出文字摘要")
    content_artifact_ref: str | None = Field(None, description="上游内容产出成果引用")
    artifact_refs: list[str] = Field(default_factory=list, description="输入产物引用")
    skill_refs: list[str] = Field(default_factory=list, description="数字资产引擎登记的技能引用")
    skill_requirements: list[dict] = Field(default_factory=list, description="本次任务需要取用的技能类型")
    digital_asset_interface_slot: dict = Field(default_factory=dict, description="数字资产引擎对接接口位")
    model_dispatch_interface_slot: dict = Field(default_factory=dict, description="1.5 大模型调度模块对接接口位；本地版仍可用 LLM 直连临时代替")
    task_adaptation: dict = Field(default_factory=dict, description="本引擎边界内的任务归一、缺项提示和承办说明")
    decision_id: str | None = None
    audit_ref: str | None = None


class MultimediaSubtaskRequest(BaseModel):
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
    actor_id: str | None = None
    task_type: str | None = None
    capability_id: str | None = None
    output_type: str | None = None
    requirement: str | None = None
    top_k: int = Field(10, ge=1, le=20)
    use_llm: bool = True
    source_engine: str | None = None
    source_engine_name: str | None = None
    parent_flow_id: str | None = None
    upstream_content_task_id: str | None = None
    upstream_content_summary: str | None = None
    content_artifact_ref: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    skill_refs: list[str] = Field(default_factory=list)
    skill_requirements: list[dict] = Field(default_factory=list)
    digital_asset_interface_slot: dict = Field(default_factory=dict)
    model_dispatch_interface_slot: dict = Field(default_factory=dict)
    task_adaptation: dict = Field(default_factory=dict)
    decision_id: str | None = None
    audit_ref: str | None = None


class ConfigUpdateRequest(BaseModel):
    kb_base: str | None = None
    llm_protocol: str | None = None
    litellm_base: str | None = None
    kimi_model: str | None = None
    litellm_key: str | None = None
