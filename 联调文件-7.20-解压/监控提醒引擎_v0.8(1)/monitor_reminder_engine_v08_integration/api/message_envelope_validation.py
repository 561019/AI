from __future__ import annotations

from datetime import datetime
from typing import Any

from api.capability_router import get_capability, load_manifest


REQUIRED_TEXT_FIELDS = (
    "protocol_version",
    "message_id",
    "trace_id",
    "request_id",
    "action",
    "capability_id",
    "capability_dictionary_version",
    "registry_version",
    "idempotency_key",
)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_object(
    envelope: dict[str, Any],
    field: str,
    errors: list[str],
) -> dict[str, Any]:
    value = envelope.get(field)
    if not isinstance(value, dict):
        errors.append(f"{field} 必须是 JSON 对象")
        return {}
    return value


def validate_message_envelope(
    envelope: Any,
) -> list[str]:
    if not isinstance(envelope, dict):
        return ["统一消息信封必须是 JSON 对象"]

    errors: list[str] = []
    for field in REQUIRED_TEXT_FIELDS:
        if not _text(envelope.get(field)):
            errors.append(f"缺少必要字段或字段为空：{field}")

    if envelope.get("protocol_version") not in (None, "1.0"):
        errors.append("protocol_version 当前仅支持 1.0")

    source = _check_object(envelope, "source", errors)
    target = _check_object(envelope, "target", errors)
    actor = _check_object(envelope, "actor", errors)
    context = _check_object(envelope, "context", errors)

    for name, obj, fields in (
        ("source", source, ("layer", "service_code")),
        ("target", target, ("layer", "service_code")),
        ("actor", actor, ("person_id", "tenant_id")),
        (
            "context",
            context,
            ("workflow_instance_id", "node_id", "task_id"),
        ),
    ):
        for field in fields:
            if not _text(obj.get(field)):
                errors.append(f"{name}.{field} 缺失或为空")

    manifest = load_manifest()
    accepted = manifest.get("accepted_source", {})

    if source:
        if source.get("layer") != accepted.get("layer"):
            errors.append("source.layer 必须为 L2")
        if source.get("service_code") != accepted.get("service_code"):
            errors.append(
                "source.service_code 必须为 l2.workflow_execution"
            )

    if target:
        if target.get("layer") != "L2":
            errors.append("target.layer 必须为 L2")
        if target.get("service_code") != manifest.get("service_code"):
            errors.append(
                "target.service_code 必须为 l2.monitor_reminder"
            )

    if envelope.get("channel") != accepted.get("channel"):
        errors.append("channel 必须为 l2_internal")

    if envelope.get("route_type") != accepted.get("route_type"):
        errors.append("route_type 必须为 task.dispatch")

    action = str(envelope.get("action", ""))
    capability_id = str(envelope.get("capability_id", ""))
    if action and capability_id and get_capability(capability_id, action) is None:
        errors.append("capability_id 与 action 未在能力登记中匹配")

    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        errors.append("payload 必须是 JSON 对象")

    deadline_at = envelope.get("deadline_at")
    if deadline_at:
        if not _text(deadline_at):
            errors.append("deadline_at 必须是 ISO 8601 字符串")
        else:
            try:
                datetime.fromisoformat(
                    deadline_at.replace("Z", "+00:00")
                )
            except ValueError:
                errors.append("deadline_at 格式不符合 ISO 8601")

    return errors
