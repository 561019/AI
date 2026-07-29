from datetime import datetime

from db import get_conn
from repositories.governance_policy_repository import (
    resolve_dnd_policy,
    resolve_escalation_policy,
)
from repositories.template_repository import resolve_template


def create_monitor_item(subtask: dict):
    payload = subtask.get("payload", {})
    required_fields = [
        "item_id",
        "object_type",
        "object_id",
        "rule_id",
        "receiver_role",
    ]

    for field in required_fields:
        if not payload.get(field):
            return {
                "status": "无法办理",
                "reason": f"缺少必要字段：{field}",
            }

    try:
        template = resolve_template(
            template_id=payload.get("template_id", ""),
            template_version=payload.get("template_version", ""),
            object_type=payload.get("object_type", ""),
        )
        dnd_policy = resolve_dnd_policy(
            payload.get("dnd_rule_ref", "DND_NONE")
        )
        escalation_policy = resolve_escalation_policy(
            payload.get("escalation_rule_ref", "ESC_NONE")
        )
    except ValueError as exc:
        return {
            "status": "无法办理",
            "reason": str(exc),
        }

    dedup_key = payload.get("dedup_key", "") or (
        f"{payload['object_id']}::{payload['rule_id']}"
    )
    merge_key = payload.get("merge_key", "") or dedup_key

    now = datetime.now().isoformat(timespec="seconds")
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT OR REPLACE INTO monitor_item (
            item_id,
            trace_id,
            object_type,
            object_id,
            rule_id,
            trigger_time,
            rule_version,
            receiver_role,
            delivery_channel,
            notice_type,
            alert_level,
            dedup_key,
            repeat_interval,
            merge_key,
            merge_window,
            dnd_rule_ref,
            escalation_rule_ref,
            template_id,
            template_version,
            status,
            created_at,
            updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            payload["item_id"],
            subtask["trace_id"],
            payload["object_type"],
            payload["object_id"],
            payload["rule_id"],
            payload.get("trigger_time", ""),
            payload.get("rule_version", "v1.0"),
            payload["receiver_role"],
            payload.get("delivery_channel", "platform_notice"),
            payload.get("notice_type", "预警通知"),
            payload.get("alert_level", "warning"),
            dedup_key,
            payload.get("repeat_interval", 600),
            merge_key,
            payload.get("merge_window", 300),
            dnd_policy["rule_ref"],
            escalation_policy["rule_ref"],
            template["template_id"],
            template["template_version"],
            "enabled",
            now,
            None,
        ),
    )

    conn.commit()
    conn.close()

    return {
        "status": "已完成",
        "item_id": payload["item_id"],
        "template_id": template["template_id"],
        "template_version": template["template_version"],
        "merge_key": merge_key,
        "merge_window": payload.get("merge_window", 300),
        "dnd_rule_ref": dnd_policy["rule_ref"],
        "escalation_rule_ref": escalation_policy["rule_ref"],
        "message": "监控项登记成功",
    }


def disable_monitor_item(item_id: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE monitor_item
        SET status = ?, updated_at = ?
        WHERE item_id = ?
        """,
        (
            "disabled",
            datetime.now().isoformat(timespec="seconds"),
            item_id,
        ),
    )

    conn.commit()
    affected = cur.rowcount
    conn.close()

    if affected == 0:
        return {
            "status": "无法办理",
            "reason": "监控项不存在",
        }

    return {
        "status": "已完成",
        "item_id": item_id,
        "message": "监控项已停用",
    }
