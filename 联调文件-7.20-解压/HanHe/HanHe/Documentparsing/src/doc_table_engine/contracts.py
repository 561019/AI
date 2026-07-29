"""Platform-facing contracts for the document parsing capability.

The parsing engine is an L2 capability.  It receives an authorized task and
artifact reference; it never receives a model credential or a database URL.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


PROTOCOL_VERSION = "1.0"
DOCUMENT_PARSE_CAPABILITY = "CAP.DOCUMENT.PARSE"


def new_message_id(prefix: str = "msg") -> str:
    return f"{prefix}_{uuid4().hex}"


class ServiceAddress(BaseModel):
    layer: Literal["L1", "L2", "L4"]
    service_code: str


class Actor(BaseModel):
    person_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    roles: list[str] = Field(default_factory=list)


class ArtifactRef(BaseModel):
    ref_id: str = Field(min_length=1)
    resource_type: str = "document"
    source_system: str = "l1.data"
    storage_key: str = Field(min_length=1)
    original_name: str = Field(min_length=1)
    version: str = "1"
    media_type: str | None = None
    data_labels: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=lambda: ["read"])
    expires_at: datetime | None = None


class ParseContext(BaseModel):
    workflow_instance_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    project_id: str | None = None
    artifact_refs: list[ArtifactRef] = Field(min_length=1)


class DocumentParseCommand(BaseModel):
    protocol_version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    message_id: str = Field(default_factory=new_message_id)
    trace_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    parent_message_id: str | None = None
    source: ServiceAddress
    target: ServiceAddress
    channel: Literal["l2_internal", "l2_to_l1"] = "l2_internal"
    route_type: Literal["task.dispatch"] = "task.dispatch"
    action: Literal["document.parse"] = "document.parse"
    capability_id: Literal[DOCUMENT_PARSE_CAPABILITY] = DOCUMENT_PARSE_CAPABILITY
    capability_dictionary_version: str = Field(min_length=1)
    registry_version: str = Field(min_length=1)
    actor: Actor
    context: ParseContext
    idempotency_key: str = Field(min_length=1)
    deadline_at: datetime
    confidence_threshold: float = Field(default=0.85, ge=0, le=1)
    template_id: str | None = None
    template_version: str | None = None


class PlatformReply(BaseModel):
    protocol_version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    reply_type: Literal["accepted", "success", "failed"]
    message_id: str = Field(default_factory=lambda: new_message_id("reply"))
    trace_id: str
    request_id: str
    parent_message_id: str
    source: ServiceAddress
    target: ServiceAddress
    task_id: str | None = None
    status: str
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
