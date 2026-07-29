from __future__ import annotations

from typing import Any

from repositories.governance_policy_repository import (
    resolve_dnd_policy,
    resolve_escalation_policy,
)
from repositories.template_repository import resolve_template
from repositories.monitor_item_repository import (
    get_monitor_item,
    list_monitor_items,
    set_monitor_item_status,
    update_monitor_item,
)


STATUS_TEXT = {
    "enabled": "启用",
    "paused": "暂停",
    "disabled": "停用",
}


def query_monitor_items(
    *,
    status: str = "",
    keyword: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    return list_monitor_items(
        status=status,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )


def query_monitor_item(
    item_id: str,
) -> dict[str, Any]:
    item = get_monitor_item(item_id)

    if item is None:
        return {
            "outcome": "not_found",
            "business_status": "无法办理",
            "message": "监控项不存在",
            "item_id": item_id,
        }

    return {
        "outcome": "found",
        "business_status": "已完成",
        "message": "监控项查询成功",
        "item": item,
    }


def modify_monitor_item(
    item_id: str,
    request_data: dict[str, Any],
) -> dict[str, Any]:
    current_item = get_monitor_item(item_id)

    if current_item is None:
        return {
            "outcome": "not_found",
            "business_status": "无法办理",
            "message": "监控项不存在",
            "item_id": item_id,
        }

    if current_item["trace_id"] != request_data["trace_id"]:
        return {
            "outcome": "trace_mismatch",
            "business_status": "无法办理",
            "message": "请求 trace_id 与监控项登记 trace_id 不一致",
            "item_id": item_id,
            "registered_trace_id": current_item["trace_id"],
        }

    updates = dict(request_data["updates"])

    if "template_id" in updates or "template_version" in updates:
        try:
            template = resolve_template(
                template_id=updates.get(
                    "template_id",
                    current_item.get("template_id", ""),
                ),
                template_version=updates.get(
                    "template_version",
                    current_item.get("template_version", ""),
                ),
                object_type=current_item.get("object_type", ""),
            )
        except ValueError as exc:
            return {
                "outcome": "invalid_template",
                "business_status": "无法办理",
                "message": str(exc),
                "item_id": item_id,
            }

        updates["template_id"] = template["template_id"]
        updates["template_version"] = template["template_version"]

    if "dnd_rule_ref" in updates:
        try:
            updates["dnd_rule_ref"] = resolve_dnd_policy(
                updates["dnd_rule_ref"]
            )["rule_ref"]
        except ValueError as exc:
            return {
                "outcome": "invalid_governance_policy",
                "business_status": "无法办理",
                "message": str(exc),
                "item_id": item_id,
            }

    if "escalation_rule_ref" in updates:
        try:
            updates["escalation_rule_ref"] = resolve_escalation_policy(
                updates["escalation_rule_ref"]
            )["rule_ref"]
        except ValueError as exc:
            return {
                "outcome": "invalid_governance_policy",
                "business_status": "无法办理",
                "message": str(exc),
                "item_id": item_id,
            }

    updated_item = update_monitor_item(
        item_id,
        updates,
    )

    return {
        "outcome": "updated",
        "business_status": "已完成",
        "message": "监控项修改成功",
        "item": updated_item,
        "changed_fields": sorted(updates.keys()),
    }


def change_monitor_item_status(
    item_id: str,
    request_data: dict[str, Any],
    target_status: str,
) -> dict[str, Any]:
    current_item = get_monitor_item(item_id)

    if current_item is None:
        return {
            "outcome": "not_found",
            "business_status": "无法办理",
            "message": "监控项不存在",
            "item_id": item_id,
        }

    if current_item["trace_id"] != request_data["trace_id"]:
        return {
            "outcome": "trace_mismatch",
            "business_status": "无法办理",
            "message": "请求 trace_id 与监控项登记 trace_id 不一致",
            "item_id": item_id,
            "registered_trace_id": current_item["trace_id"],
        }

    if target_status not in STATUS_TEXT:
        return {
            "outcome": "invalid_transition",
            "business_status": "无法办理",
            "message": f"不支持的监控项状态：{target_status}",
            "item_id": item_id,
        }

    current_status = current_item["status"]
    if current_status == target_status:
        return {
            "outcome": "already_in_state",
            "business_status": "已完成",
            "message": (
                f"监控项已经处于{STATUS_TEXT[target_status]}状态"
            ),
            "item": current_item,
        }

    if target_status == "paused" and current_status != "enabled":
        return {
            "outcome": "invalid_transition",
            "business_status": "无法办理",
            "message": (
                "只有启用状态的监控项可以暂停，"
                f"当前状态：{current_status}"
            ),
            "item_id": item_id,
        }

    if (
        target_status == "enabled"
        and request_data.get("status_action") == "resume"
        and current_status != "paused"
    ):
        return {
            "outcome": "invalid_transition",
            "business_status": "无法办理",
            "message": (
                "只有暂停状态的监控项可以恢复，"
                f"当前状态：{current_status}"
            ),
            "item_id": item_id,
        }

    updated_item = set_monitor_item_status(
        item_id,
        target_status,
    )

    outcome_by_status = {
        "enabled": "enabled",
        "paused": "paused",
        "disabled": "disabled",
    }

    return {
        "outcome": outcome_by_status[target_status],
        "business_status": "已完成",
        "message": f"监控项{STATUS_TEXT[target_status]}成功",
        "item": updated_item,
    }
