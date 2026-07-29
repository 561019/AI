from __future__ import annotations

from pydantic import BaseModel, Field


class FlowStartRequest(BaseModel):
    actor_id: str = Field("U001", description="当前责任真人")
    source_module: str = Field("local_l4_demo", description="上游来源模块")
    workflow_type: str = Field(
        "media_only",
        description="media_only / content_then_media / hot_case_batch / hot_case_sample_then_batch / expert_agent_plan / skill_promotion_authorization",
    )
    requirement: str = Field(..., description="已确认的 L4 原始需求或结构化任务描述")
    task_type: str = Field("multimedia_poster", description="传给多媒体/知识库的取材任务类型")
    capability_id: str = Field("text_to_image", description="多媒体能力接口位")
    output_type: str = Field("poster_plan", description="多媒体输出类型")
    top_k: int = Field(8, ge=1, le=20)
    use_llm: bool = Field(True, description="是否要求多媒体真实调用 LLM")
    review_policy: str = Field("always", description="always / none；本地版默认真人确认")
    batch_count: int = Field(3, ge=1, le=5, description="批量爆款生成数量，仅 hot_case_batch 使用")
    hot_case_refs: list[str] = Field(default_factory=lambda: ["HOT-CASE-001"], description="爆款案例引用")
    skill_refs: list[str] = Field(
        default_factory=lambda: ["SKILL-HOT-CASE-PATTERN-001", "SKILL-HOT-CASE-STANDARD-001"],
        description="数字资产引擎登记的爆款模式/制作标准技能引用；本地仅作为接口位传递",
    )
    expert_agent_ref: str = Field("AGENT-CROP-NUTRITION-001", description="共享池专家分身引用；本地仅作为接口位传递")
    project_id: str = Field("PROJECT-DEMO-001", description="项目/会话归属标识")
    share_scope: str = Field("region_pool", description="技能推广目标范围，例如 region_pool / group_pool")
    idempotency_key: str = Field("", description="预留幂等键")


class HumanDecisionRequest(BaseModel):
    instance_id: str
    task_id: str
    decision: str = Field(..., description="approved / rejected")
    comment: str = ""
    decided_by: str = "U001"


class ConfigUpdateRequest(BaseModel):
    media_base: str | None = None
    content_base: str | None = None
    request_timeout_seconds: int | None = None


class FlowCallbackRequest(BaseModel):
    trace_id: str | None = None
    workflow_instance_id: str | None = None
    node_id: str | None = None
    task_id: str
    idempotency_key: str | None = None
    source_service: str | None = None
    status: str
    result: dict = Field(default_factory=dict)
    error: dict | str | None = None
    audit_ref: str | None = None
    completed_at: str | None = None
