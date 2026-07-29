from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class Actor(BaseModel):
    person_id: str
    tenant_id: str = "tenant_hanhe"
    position_code: Optional[str] = None


class Endpoint(BaseModel):
    layer: str
    service_code: str


class MessageContext(BaseModel):
    workflow_instance_id: Optional[str] = None
    node_id: Optional[str] = None
    task_id: Optional[str] = None
    data_refs: list[dict[str, Any]] = Field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)


class InternalMessage(BaseModel):
    protocol_version: str = "1.0"
    message_id: str
    parent_message_id: Optional[str] = None
    trace_id: str
    request_id: str
    source: Endpoint
    target: Endpoint
    channel: str = "l2_internal"
    route_type: str
    action: str
    capability_id: str
    capability_dictionary_version: str = "2026.07.v06"
    registry_version: str = "registry_2026.07.v06"
    actor: Actor
    context: MessageContext = Field(default_factory=MessageContext)
    idempotency_key: str
    deadline_at: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
