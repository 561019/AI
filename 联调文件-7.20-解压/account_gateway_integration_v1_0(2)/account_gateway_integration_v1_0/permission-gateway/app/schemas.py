from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PermissionCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    trace_id: str = Field(min_length=1, max_length=255)
    request_id: str = Field(min_length=1, max_length=255)
    actor_id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=128)
    source_service: str = Field(min_length=1, max_length=128)
    target_service: str = Field(min_length=1, max_length=128)
    data_label: str = Field(min_length=1, max_length=128)
    data_state: str = Field(min_length=1, max_length=32)
    tenant_id: str | None = Field(default=None, max_length=128)
    person_id: str | None = Field(default=None, max_length=128)
    position_id: str | None = Field(default=None, max_length=128)
    resource_type: str | None = Field(default=None, max_length=128)
    resource_id: str | None = Field(default=None, max_length=255)
    domain_id: str | None = Field(default=None, max_length=128)
    requested_at: datetime | None = None
    responsible_actor_id: str | None = Field(default=None, max_length=128)
    executor_type: Literal["human", "agent", "system"] = "human"
    executor_id: str | None = Field(default=None, max_length=128)
    ingress_mode: Literal["mechanism_direct"] | None = None
    original_caller_service_id: str | None = Field(default=None, max_length=128)
    transfer_id: str | None = Field(default=None, max_length=255)
    service_registry_version: str | None = Field(default=None, max_length=64)
    identity_context_hash: str | None = Field(default=None, max_length=128)
    # Populated only by the L1 interface after it verifies account-gateway facts.
    identity_position_ids: list[str] = Field(default_factory=list, max_length=64)
    identity_managed_person_ids: list[str] = Field(default_factory=list, max_length=10000)

    @field_validator(
        "tenant_id", "person_id", "position_id", "resource_type", "resource_id", "domain_id",
        "responsible_actor_id", "executor_id", "original_caller_service_id", "transfer_id",
        "service_registry_version", "identity_context_hash"
    )
    @classmethod
    def empty_optional_to_none(cls, value: str | None) -> str | None:
        return value or None


class FourFactors(BaseModel):
    data_label: str
    action: str
    actor_id: str
    data_state: str


class PermissionError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class PermissionCheckResponse(BaseModel):
    trace_id: str
    request_id: str
    decision_id: str | None
    allowed: bool
    result: Literal["allow", "deny", "error"]
    reason_code: str
    reason: str
    four_factors: FourFactors | None
    error: PermissionError | None = None
    decided_at: datetime


class AuditItem(BaseModel):
    id: int
    decision_id: str | None
    trace_id: str
    request_id: str
    actor_id: str
    person_id: str | None
    position_id: str | None
    tenant_id: str | None
    action: str
    source_service: str
    target_service: str
    resource_type: str | None
    resource_id: str | None
    data_label: str
    data_state: str
    allowed: bool
    result: str
    reason_code: str
    reason: str
    policy_id: str | None
    four_factors: dict[str, Any] | None
    error: dict[str, Any] | None
    requested_at: datetime
    decided_at: datetime
    responsible_actor_id: str | None = None
    executor_type: str | None = None
    executor_id: str | None = None
    original_caller_service_id: str | None = None
    ingress_mode: str | None = None
    transfer_id: str | None = None
    identity_context_hash: str | None = None


class AuditListResponse(BaseModel):
    audits: list[AuditItem]
    next_after_id: int | None


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)


class IntegrationEventRequest(BaseModel):
    """Reserved asynchronous event envelope; v1 does not process events yet."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event_id: str = Field(min_length=1, max_length=255)
    event_type: str = Field(min_length=1, max_length=128)
    occurred_at: datetime
    source_service: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    actor_id: str | None = Field(default=None, max_length=128)
    resource_type: str | None = Field(default=None, max_length=128)
    resource_id: str | None = Field(default=None, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)
