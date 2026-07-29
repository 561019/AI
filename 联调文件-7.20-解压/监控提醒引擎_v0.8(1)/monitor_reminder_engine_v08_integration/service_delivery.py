from __future__ import annotations

from datetime import datetime
from typing import Any

from db import get_conn
from repositories.template_repository import (
    render_template,
    resolve_template,
)


from adapters.mock_account_gateway import resolve_current_holder
from adapters.mock_notification_channel import send_notification


def render_notice(
    item: dict[str, Any],
    judgement: dict[str, Any],
) -> dict[str, Any]:
    scene_type = judgement.get("scene_type", "general")
    template = resolve_template(
        template_id=item.get("template_id", ""),
        template_version=item.get("template_version", ""),
        scene_type=scene_type,
        object_type=item.get("object_type", ""),
    )

    values = {
        **item,
        **judgement,
        "trace_id": judgement.get("trace_id", item.get("trace_id", "")),
        "alert_level": item.get("alert_level", "warning"),
    }
    content = render_template(template, values)

    trigger_value = judgement.get("trigger_value")
    if trigger_value in (None, ""):
        trigger_value = judgement.get("actual_value", "")

    return {
        "content": content,
        "template_id": template["template_id"],
        "template_version": template["template_version"],
        "alert_level": item.get("alert_level", "warning"),
        "trigger_value": "" if trigger_value is None else str(trigger_value),
    }


def generate_notice_content(item: dict, judgement: dict):
    return render_notice(item, judgement)["content"]


def _latest_reminder_id(
    trace_id: str,
    item_id: str,
) -> int | None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id
            FROM reminder_record
            WHERE trace_id = ? AND item_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (trace_id, item_id),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()


def deliver_notice(
    item_id: str,
    judgement: dict,
    content: str,
    template_metadata: dict[str, Any] | None = None,
    governance_result: dict[str, Any] | None = None,
):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM monitor_item
        WHERE item_id = ?
        """,
        (item_id,),
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        return {
            "status": "无法办理",
            "reason": "监控项不存在",
        }

    item = dict(row)
    account_result = resolve_current_holder(
        item["receiver_role"],
        tenant_id=str(judgement.get("tenant_id", "tenant_hanhe")),
    )
    receiver_user = account_result.get("display_name", "")

    if not account_result.get("found") or not account_result.get(
        "receive_qualified"
    ):
        cur.execute(
            """
            INSERT INTO delivery_record (
                reminder_id,
                trace_id,
                item_id,
                receiver_role,
                receiver_user,
                delivery_status,
                reason,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                None,
                judgement["trace_id"],
                item_id,
                item["receiver_role"],
                "",
                "无法送达",
                "账号网关未找到符合接收资格的当前在任真人",
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        conn.close()
        return {
            "status": "无法办理",
            "reason": "账号网关未找到符合接收资格的当前在任真人",
        }

    metadata = template_metadata or render_notice(item, judgement)
    now = datetime.now().isoformat(timespec="seconds")

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
            judgement["trace_id"],
            item_id,
            judgement["reason"],
            content,
            "待确认",
            metadata.get("template_id", ""),
            metadata.get("template_version", ""),
            metadata.get("alert_level", item.get("alert_level", "warning")),
            metadata.get("trigger_value", ""),
            (governance_result or {}).get("event_id", ""),
            (governance_result or {}).get("decision", "send"),
            (governance_result or {}).get(
                "governance_result",
                "治理检查通过，允许发送",
            ),
            (governance_result or {}).get("merged_into_reminder_id"),
            (governance_result or {}).get(
                "dnd_rule_ref",
                item.get("dnd_rule_ref", "DND_NONE"),
            ),
            (governance_result or {}).get(
                "escalation_rule_ref",
                item.get("escalation_rule_ref", "ESC_NONE"),
            ),
            (governance_result or {}).get("next_eligible_at", ""),
            now,
        ),
    )
    reminder_id = int(cur.lastrowid)

    notification_result = send_notification(
        trace_id=judgement["trace_id"],
        reminder_id=reminder_id,
        receiver_role=item["receiver_role"],
        receiver_person_id=account_result.get("person_id", ""),
        receiver_name=receiver_user,
        channel=item.get("delivery_channel", "platform_notice"),
        content=content,
        simulate_failure=bool(
            judgement.get("simulate_notification_failure", False)
        ),
    )

    cur.execute(
        """
        INSERT INTO delivery_record (
            reminder_id,
            trace_id,
            item_id,
            receiver_role,
            receiver_user,
            delivery_status,
            reason,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            reminder_id,
            judgement["trace_id"],
            item_id,
            item["receiver_role"],
            receiver_user,
            notification_result["delivery_status"],
            notification_result["reason"],
            now,
        ),
    )

    conn.commit()
    conn.close()

    if not notification_result.get("delivered"):
        return {
            "status": "无法办理",
            "reason": notification_result.get(
                "reason",
                "通知通道送达失败",
            ),
            "reminder_id": reminder_id,
            "receiver_role": item["receiver_role"],
            "receiver_user": receiver_user,
            "account_resolution_id": account_result.get(
                "resolution_id",
                "",
            ),
            "notification_id": notification_result.get(
                "notification_id",
                "",
            ),
            "notification_sent": False,
        }

    return {
        "status": "待真人确认",
        "reminder_id": reminder_id,
        "receiver_role": item["receiver_role"],
        "receiver_user": receiver_user,
        "receiver_person_id": account_result.get("person_id", ""),
        "account_resolution_id": account_result.get("resolution_id", ""),
        "notification_id": notification_result.get("notification_id", ""),
        "notification_sent": True,
        "content": content,
        "template_id": metadata.get("template_id", ""),
        "template_version": metadata.get("template_version", ""),
        "governance_action": (governance_result or {}).get(
            "decision",
            "send",
        ),
        "governance_result": (governance_result or {}).get(
            "governance_result",
            "治理检查通过，允许发送",
        ),
        "dnd_rule_ref": (governance_result or {}).get(
            "dnd_rule_ref",
            item.get("dnd_rule_ref", "DND_NONE"),
        ),
        "escalation_rule_ref": (governance_result or {}).get(
            "escalation_rule_ref",
            item.get("escalation_rule_ref", "ESC_NONE"),
        ),
    }


def simulate_confirm(
    trace_id: str,
    item_id: str,
    user: str,
    reminder_id: int | None = None,
):
    resolved_id = reminder_id or _latest_reminder_id(trace_id, item_id)
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO confirm_record (
            reminder_id,
            trace_id,
            item_id,
            confirm_user,
            confirm_status,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            resolved_id,
            trace_id,
            item_id,
            user,
            "已确认",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )

    conn.commit()
    conn.close()

    return {
        "status": "已完成",
        "message": "真人确认记录已追加，原提醒记录保持不变",
    }


def simulate_recovery(
    trace_id: str,
    item_id: str,
    user: str,
    reminder_id: int | None = None,
):
    resolved_id = reminder_id or _latest_reminder_id(trace_id, item_id)
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO recovery_record (
            reminder_id,
            trace_id,
            item_id,
            recovery_status,
            created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            resolved_id,
            trace_id,
            item_id,
            f"已由 {user} 确认处理完成，恢复销记",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )

    conn.commit()
    conn.close()

    return {
        "status": "已完成",
        "message": "恢复销记记录已追加",
    }


def simulate_escalation(
    trace_id: str,
    item_id: str,
    escalation_role: str,
    reason: str,
    reminder_id: int | None = None,
):
    resolved_id = reminder_id or _latest_reminder_id(trace_id, item_id)
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO escalation_record (
            reminder_id,
            trace_id,
            item_id,
            escalation_role,
            reason,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            resolved_id,
            trace_id,
            item_id,
            escalation_role,
            reason,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )

    conn.commit()
    conn.close()

    return {
        "status": "待真人确认",
        "message": f"已升级催办至 {escalation_role}",
        "reason": reason,
    }
