from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    actor_id: str = Field(..., description="当前操作真人/演示用户")
    query: str = Field(..., description="检索问题或任务描述")
    top_k: int = Field(5, ge=1, le=20)
    types: list[str] = Field(default_factory=list, description="限定资料类型")
    tags: list[str] = Field(default_factory=list, description="限定标签")


class TaskMaterialRequest(BaseModel):
    actor_id: str
    task_type: str = Field(..., description="任务类型，如 marketing_bundle/rectification_notice/legal_pleading/multimedia_poster")
    query: str = ""
    top_k: int = Field(8, ge=1, le=20)
    include_templates: bool = True


class ItemCreateRequest(BaseModel):
    material_id: str
    title: str
    type: str
    summary: str
    content: str
    source: str
    version: str = "v0.1"
    tags: list[str] = Field(default_factory=list)
    permission_scope: list[str] = Field(default_factory=lambda: ["public"])
    citation: str
    updated_at: str
