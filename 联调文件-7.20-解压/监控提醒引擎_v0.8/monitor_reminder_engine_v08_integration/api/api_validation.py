from __future__ import annotations

from datetime import datetime
from typing import Any


COMMON_REQUIRED_FIELDS = (
    "request_id",
    "trace_id",
    "source_module",
    "timestamp",
)

MONITOR_ITEM_REQUIRED_FIELDS = (
    "item_id",
    "object_type",
    "object_id",
    "rule_id",
    "receiver_role",
)

TRIGGER_RESULT_REQUIRED_FIELDS = (
    "triggered",
    "rule_id",
    "rule_version",
    "reason",
)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_valid_timestamp(value: Any) -> bool:
    if not _is_non_empty_string(value):
        return False

    normalized = value.strip().replace("Z", "+00:00")

    try:
        datetime.fromisoformat(normalized)
        return True
    except ValueError:
        return False


def _validate_common_fields(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    for field in COMMON_REQUIRED_FIELDS:
        if not _is_non_empty_string(data.get(field)):
            errors.append(f"缺少必要字段或字段为空：{field}")

    timestamp = data.get("timestamp")
    if timestamp and not _is_valid_timestamp(timestamp):
        errors.append(
            "timestamp 格式不正确，应使用 ISO 8601，"
            "例如 2026-07-14T20:30:00"
        )

    return errors


def validate_monitor_item_request(data: Any) -> list[str]:
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["请求体必须是 JSON 对象"]

    errors.extend(_validate_common_fields(data))

    payload = data.get("payload")
    if not isinstance(payload, dict):
        errors.append("payload 必须是 JSON 对象")
        return errors

    for field in MONITOR_ITEM_REQUIRED_FIELDS:
        if not _is_non_empty_string(payload.get(field)):
            errors.append(f"payload 缺少必要字段或字段为空：{field}")

    repeat_interval = payload.get("repeat_interval", 600)
    if isinstance(repeat_interval, bool) or not isinstance(repeat_interval, int):
        errors.append("payload.repeat_interval 必须是整数")
    elif repeat_interval < 0:
        errors.append("payload.repeat_interval 不能小于 0")

    merge_window = payload.get("merge_window", 300)
    if isinstance(merge_window, bool) or not isinstance(merge_window, int):
        errors.append("payload.merge_window 必须是整数")
    elif merge_window < 0:
        errors.append("payload.merge_window 不能小于 0")

    for field in (
        "template_id",
        "template_version",
        "merge_key",
        "dnd_rule_ref",
        "escalation_rule_ref",
    ):
        value = payload.get(field)
        if value is not None and not _is_non_empty_string(value):
            errors.append(f"payload.{field} 必须是非空字符串")

    return errors


def build_register_subtask(data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data["payload"])

    return {
        "task_id": data.get("task_id") or data["request_id"],
        "subtask_id": data.get("subtask_id")
        or f"SUB_{data['request_id']}",
        "subtask_type": "登记维护类",
        "trace_id": data["trace_id"],
        "request_type": "create_monitor_item",
        "source_module": data["source_module"],
        "operator_id": data.get("operator_id", ""),
        "request_timestamp": data["timestamp"],
        "payload": payload,
    }


def validate_reminder_trigger_request(data: Any) -> list[str]:
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["请求体必须是 JSON 对象"]

    errors.extend(_validate_common_fields(data))

    if not _is_non_empty_string(data.get("item_id")):
        errors.append("缺少必要字段或字段为空：item_id")

    judgement_result = data.get("judgement_result")
    if not isinstance(judgement_result, dict):
        errors.append("judgement_result 必须是 JSON 对象")
        return errors

    for field in TRIGGER_RESULT_REQUIRED_FIELDS:
        value = judgement_result.get(field)

        if field == "triggered":
            if not isinstance(value, bool):
                errors.append("judgement_result.triggered 必须是布尔值")
            continue

        if not _is_non_empty_string(value):
            errors.append(
                "judgement_result 缺少必要字段或字段为空："
                f"{field}"
            )

    return errors


def build_judgement_data(
    data: dict[str, Any],
) -> dict[str, Any]:
    judgement_result = dict(data["judgement_result"])
    triggered = judgement_result.pop("triggered")

    return {
        "task_id": data.get("task_id") or data["request_id"],
        "subtask_id": data.get("subtask_id")
        or f"SUB_{data['request_id']}",
        "subtask_type": "提醒办理类",
        "trace_id": data["trace_id"],
        "item_id": data["item_id"],
        "judgement_result": (
            "triggered" if triggered else "not_triggered"
        ),
        **judgement_result,
    }


def validate_reminder_action_request(
    data: Any,
    action: str,
) -> list[str]:
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["请求体必须是 JSON 对象"]

    errors.extend(_validate_common_fields(data))

    required_by_action = {
        "confirm": ("confirm_user",),
        "recover": ("recovery_user",),
        "escalate": ("escalation_role", "reason"),
    }

    required_fields = required_by_action.get(action)
    if required_fields is None:
        return [f"不支持的提醒操作：{action}"]

    for field in required_fields:
        if not _is_non_empty_string(data.get(field)):
            errors.append(f"缺少必要字段或字段为空：{field}")

    return errors



MONITOR_ITEM_UPDATE_FIELDS = {
    "trigger_time",
    "rule_version",
    "receiver_role",
    "delivery_channel",
    "notice_type",
    "alert_level",
    "dedup_key",
    "repeat_interval",
    "merge_key",
    "merge_window",
    "dnd_rule_ref",
    "escalation_rule_ref",
    "template_id",
    "template_version",
}


def validate_monitor_item_update_request(
    data: Any,
) -> list[str]:
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["请求体必须是 JSON 对象"]

    errors.extend(_validate_common_fields(data))

    updates = data.get("updates")
    if not isinstance(updates, dict):
        errors.append("updates 必须是 JSON 对象")
        return errors

    if not updates:
        errors.append("updates 至少包含一个待修改字段")
        return errors

    unsupported_fields = sorted(
        set(updates) - MONITOR_ITEM_UPDATE_FIELDS
    )

    if unsupported_fields:
        errors.append(
            "存在不允许修改的字段："
            + "、".join(unsupported_fields)
        )

    for numeric_field in ("repeat_interval", "merge_window"):
        numeric_value = updates.get(numeric_field)
        if numeric_value is not None:
            if (
                isinstance(numeric_value, bool)
                or not isinstance(numeric_value, int)
            ):
                errors.append(f"updates.{numeric_field} 必须是整数")
            elif numeric_value < 0:
                errors.append(f"updates.{numeric_field} 不能小于 0")

    for field, value in updates.items():
        if field in ("repeat_interval", "merge_window"):
            continue

        if field in MONITOR_ITEM_UPDATE_FIELDS:
            if not _is_non_empty_string(value):
                errors.append(
                    f"updates.{field} 必须是非空字符串"
                )

    return errors


def validate_monitor_item_status_request(
    data: Any,
) -> list[str]:
    if not isinstance(data, dict):
        return ["请求体必须是 JSON 对象"]

    return _validate_common_fields(data)
