from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from adapters.adapter_registry import record_adapter_call


FORBIDDEN_KEYS = {
    "password",
    "passwd",
    "secret",
    "api_key",
    "access_token",
    "private_key",
    "credential",
}


def _find_forbidden_keys(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in FORBIDDEN_KEYS:
                found.append(child_path)
            found.extend(_find_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_forbidden_keys(child, f"{path}[{index}]"))
    return found


def inspect_input(
    payload: dict[str, Any],
    *,
    action: str,
    trace_id: str = "",
) -> dict[str, Any]:
    audit_ref = f"audit_sec_in_{uuid4().hex}"
    forbidden = _find_forbidden_keys(payload)
    result = {
        "allowed": not forbidden,
        "audit_ref": audit_ref,
        "action": action,
        "trace_id": trace_id,
        "obligations": ["redact_secrets", "retain_trace"],
        "violations": forbidden,
        "sanitized_payload": deepcopy(payload),
    }
    record_adapter_call(
        "security_compliance_1_9",
        "security.inspect_input",
        {
            "audit_ref": audit_ref,
            "allowed": result["allowed"],
            "action": action,
            "trace_id": trace_id,
            "violations": forbidden,
        },
    )
    return result


def inspect_output(
    payload: dict[str, Any],
    *,
    action: str,
    trace_id: str = "",
) -> dict[str, Any]:
    audit_ref = f"audit_sec_out_{uuid4().hex}"
    result = {
        "allowed": True,
        "audit_ref": audit_ref,
        "action": action,
        "trace_id": trace_id,
        "obligations": ["mask_sensitive_fields", "retain_trace"],
        "sanitized_payload": deepcopy(payload),
    }
    record_adapter_call(
        "security_compliance_1_9",
        "security.inspect_output",
        {
            "audit_ref": audit_ref,
            "allowed": True,
            "action": action,
            "trace_id": trace_id,
        },
    )
    return result
