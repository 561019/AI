from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LayerRequestEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contract_version: Literal["v1"] = "v1"
    trace_id: str = Field(min_length=1, max_length=255)
    request_id: str = Field(min_length=1, max_length=255)
    transfer_id: str = Field(min_length=1, max_length=255)
    caller_layer: Literal["L2"] = "L2"
    caller_service_id: str = Field(min_length=1, max_length=128)
    target_service_id: str = Field(min_length=1, max_length=128)
    command: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    responsible_actor_id: str | None = Field(default=None, max_length=128)
    executor_type: Literal["human", "agent", "system"]
    executor_id: str | None = Field(default=None, max_length=128)
    resource_type: str = Field(min_length=1, max_length=128)
    resource_id: str | None = Field(default=None, max_length=255)
    action: str = Field(min_length=1, max_length=128)
    data_label: str = Field(min_length=1, max_length=128)
    data_state: str = Field(min_length=1, max_length=32)
    identity_context: dict[str, Any] = Field(default_factory=dict)
    identity_context_token: str | None = Field(default=None, min_length=1, max_length=4096)
    payload: dict[str, Any] = Field(default_factory=dict)
    requested_at: datetime
    nonce: str = Field(min_length=1, max_length=255)


class LayerResponseEnvelope(BaseModel):
    trace_id: str
    request_id: str
    transfer_id: str
    status: Literal["success", "deny", "error"]
    result: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    permission_decision_id: str | None = None
    completed_at: datetime
