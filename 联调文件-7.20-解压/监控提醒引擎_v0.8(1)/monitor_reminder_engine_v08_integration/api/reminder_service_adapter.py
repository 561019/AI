from __future__ import annotations

from datetime import datetime
from typing import Any

from api.api_validation import build_judgement_data
from db import get_conn
from repositories.monitor_item_repository import get_monitor_item
from service_delivery import (
    deliver_notice,
    render_notice,
)
from service_governance import check_governance


def write_governance_record(
    *,
    trace_id: str,
    item: dict[str, Any],
    judgement: dict[str, Any],
    governance: dict[str, Any],
) -> int:
    status = governance.get("record_status", "已抑制")
    content_by_status = {
        "已合并": "本次同类提醒已合并到既有提醒，不重复发送通知。",
        "已暂缓": "本次提醒处于免打扰时段，已记录暂缓发送决定。",
        "已抑制": "本次触发被提醒治理程序抑制，不重复发送通知。",
    }

    trigger_value = judgement.get("trigger_value")
    if trigger_value in (None, ""):
        trigger_value = judgement.get("actual_value", "")

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO reminder_record (
                trace_id,
                item_id,
                reason,
                content,
                status,
                template_id,
                template_version,
                alert_level,
                trigger_value,
                event_id,
                governance_action,
                governance_reason,
                merged_into_reminder_id,
                dnd_rule_ref,
                escalation_rule_ref,
                next_eligible_at,
                created_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                trace_id,
                item["item_id"],
                governance.get("governance_result", "治理决定"),
                content_by_status.get(status, "本次提醒未发送。"),
                status,
                item.get("template_id", ""),
                item.get("template_version", ""),
                item.get("alert_level", "warning"),
                "" if trigger_value is None else str(trigger_value),
                governance.get("event_id", ""),
                governance.get("decision", "suppressed"),
                governance.get("governance_result", ""),
                governance.get("merged_into_reminder_id"),
                governance.get(
                    "dnd_rule_ref",
                    item.get("dnd_rule_ref", "DND_NONE"),
                ),
                governance.get(
                    "escalation_rule_ref",
                    item.get("escalation_rule_ref", "ESC_NONE"),
                ),
                governance.get("next_eligible_at", ""),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def process_reminder_trigger(
    request_data: dict[str, Any],
) -> dict[str, Any]:
    item_id = request_data["item_id"]
    trace_id = request_data["trace_id"]
    item = get_monitor_item(item_id)

    if item is None:
        return {
            "outcome": "not_found",
            "business_status": "无法办理",
            "message": "监控项不存在",
            "item_id": item_id,
        }

    item_status = item.get("status")
    if item_status == "paused":
        return {
            "outcome": "paused",
            "business_status": "无法办理",
            "message": "监控项已暂停，当前不办理提醒",
            "item_id": item_id,
        }

    if item_status != "enabled":
        return {
            "outcome": "disabled",
            "business_status": "无法办理",
            "message": "监控项已停用，不能触发提醒",
            "item_id": item_id,
        }

    if item.get("trace_id") != trace_id:
        return {
            "outcome": "trace_mismatch",
            "business_status": "无法办理",
            "message": "请求 trace_id 与监控项登记 trace_id 不一致",
            "item_id": item_id,
            "registered_trace_id": item.get("trace_id"),
        }

    judgement = build_judgement_data(request_data)

    if judgement["judgement_result"] != "triggered":
        return {
            "outcome": "not_triggered",
            "business_status": "已完成",
            "message": "规则计算结果为未触发，本引擎不生成提醒",
            "item_id": item_id,
            "rule_id": judgement.get("rule_id"),
            "rule_version": judgement.get("rule_version"),
        }

    governance = check_governance(item, judgement)

    if not governance.get("allow_send", False):
        governance_record_id = write_governance_record(
            trace_id=trace_id,
            item=item,
            judgement=judgement,
            governance=governance,
        )
        decision = governance.get("decision", "suppressed")
        outcome_by_decision = {
            "merged": "merged",
            "dnd_deferred": "deferred",
        }
        outcome = outcome_by_decision.get(decision, "suppressed")
        business_status = (
            "已暂缓" if decision == "dnd_deferred" else "已完成"
        )

        return {
            "outcome": outcome,
            "business_status": business_status,
            "message": governance.get(
                "governance_result",
                "提醒已被治理策略处理",
            ),
            "item_id": item_id,
            "governance_record_id": governance_record_id,
            "governance_action": decision,
            "governance_result": governance.get("governance_result"),
            "related_reminder_id": governance.get("related_reminder_id"),
            "merged_into_reminder_id": governance.get(
                "merged_into_reminder_id"
            ),
            "next_eligible_at": governance.get("next_eligible_at", ""),
            "dnd_rule_ref": governance.get("dnd_rule_ref"),
            "escalation_rule_ref": governance.get(
                "escalation_rule_ref"
            ),
            "notification_sent": False,
        }

    rendered = render_notice(item, judgement)
    delivery_result = deliver_notice(
        item_id=item_id,
        judgement=judgement,
        content=rendered["content"],
        template_metadata=rendered,
        governance_result=governance,
    )

    if delivery_result.get("status") == "无法办理":
        return {
            "outcome": "unable_to_deliver",
            "business_status": "无法办理",
            "message": delivery_result.get("reason", "通知无法送达"),
            "item_id": item_id,
            "governance_result": governance.get("governance_result"),
            "delivery_result": delivery_result,
        }

    return {
        "outcome": "notification_sent",
        "business_status": delivery_result.get(
            "status",
            "待真人确认",
        ),
        "message": "提醒已生成并通过模拟通知通道送达",
        "item_id": item_id,
        "reminder_id": delivery_result.get("reminder_id"),
        "governance_action": governance.get("decision", "send"),
        "governance_result": governance.get("governance_result"),
        "receiver_role": delivery_result.get("receiver_role"),
        "receiver_user": delivery_result.get("receiver_user"),
        "receiver_person_id": delivery_result.get("receiver_person_id", ""),
        "account_resolution_id": delivery_result.get(
            "account_resolution_id",
            "",
        ),
        "notification_id": delivery_result.get("notification_id", ""),
        "content": delivery_result.get("content", rendered["content"]),
        "template_id": delivery_result.get("template_id"),
        "template_version": delivery_result.get("template_version"),
        "dnd_rule_ref": delivery_result.get("dnd_rule_ref"),
        "escalation_rule_ref": delivery_result.get(
            "escalation_rule_ref"
        ),
        "urgent_exception": bool(governance.get("urgent_exception")),
        "notification_sent": bool(
            delivery_result.get("notification_sent", True)
        ),
    }
