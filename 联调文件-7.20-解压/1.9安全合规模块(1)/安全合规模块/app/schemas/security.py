"""安全合规模块 —— 简化版 schemas（仅 check 流程）。"""
from typing import Any, Dict, List
from pydantic import BaseModel, Field


class SecurityCheckRequest(BaseModel):
    """简化的安全检查请求：输入文本 + 身份 + 手动选项。"""
    input_text: str = Field(default="", description="用户输入文本")
    real_person_id: str = Field(default="anonymous", description="操作者真实身份ID")
    is_emergency: bool = Field(default=False, description="是否应急监察账号")
    data_classification: str = Field(default="public", description="数据密级：confidential / public")
    network: str = Field(default="intranet", description="网络环境：intranet / public")
    model_type: str = Field(default="domestic", description="模型类型：domestic / overseas / local")
    output_files: list[dict] = Field(default_factory=list, description="AI返回的文件列表")
    output_text: str = Field(default="", description="AI返回的语句")


class ViolationResult(BaseModel):
    passed: bool = True
    risk_level: str = "low"
    hit_words: List[str] = Field(default_factory=list)
    hit_rules: List[Dict[str, Any]] = Field(default_factory=list)
    suggestion: str = ""
    checked: bool = Field(default=True)


class MaskingResult(BaseModel):
    need_masking: bool = False
    masked_text: str = ""
    findings: List[Dict[str, Any]] = Field(default_factory=list)
    checked: bool = Field(default=True)


class PermissionResultV2(BaseModel):
    has_permission: bool = True
    deny_reason: str = ""
    matched_role: str = ""
    matched_domain: str = ""
    checked: bool = Field(default=True)


class DataDomainResult(BaseModel):
    can_use_external_model: bool = True
    model_scope: str = "external_allowed"
    allowed_model_tags: List[str] = Field(default_factory=lambda: ["external", "private", "local"])
    forbidden_model_tags: List[str] = Field(default_factory=list)
    hit_rules: List[Dict[str, Any]] = Field(default_factory=list)
    reason: str = ""
    checked: bool = Field(default=True)


class ModelCheckResult(BaseModel):
    passed: bool = True
    model_type: str = "domestic"
    reason: str = ""
    checked: bool = Field(default=True)


class SecurityCheckResponse(BaseModel):
    request_id: str
    audit_id: str
    trace_id: str = ""
    model_check: ModelCheckResult = Field(default_factory=ModelCheckResult)
    network_check: ViolationResult = Field(default_factory=ViolationResult)
    violation: ViolationResult = Field(description="第二层：违规词检查")
    masking: MaskingResult = Field(description="第三层：敏感词脱敏")
    data_domain: DataDomainResult = Field(default_factory=DataDomainResult)
    permission: PermissionResultV2 = Field(description="第五层：权限管理")
    decision: str = Field(description="最终决策：allow / deny")
    decision_reason: str = Field(default="", description="决策原因")
