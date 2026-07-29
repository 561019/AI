"""权限管理模块接口数据结构（简化版 —— 仅保留 check 流程所需类型）。"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CheckedFourElements(BaseModel):
    time: Optional[str] = None
    who: Optional[str] = None
    data: Optional[str] = None
    action: Optional[str] = None


class PermissionDecision(BaseModel):
    allow: bool = False
    decision: str = "deny"
    deny_reason: Optional[str] = None
    permission_source: Optional[str] = None
    matched_sources: List[str] = Field(default_factory=list)
    checked_four_elements: Optional[CheckedFourElements] = None
    audit_id: Optional[str] = None
