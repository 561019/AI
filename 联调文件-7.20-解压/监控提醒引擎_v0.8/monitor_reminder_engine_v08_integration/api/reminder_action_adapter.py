from __future__ import annotations

from typing import Any

from db import get_conn
from service_delivery import (
    simulate_confirm,
    simulate_escalation,
    simulate_recovery,
)


def get_reminder_by_id(
    reminder_id: int,
) -> dict[str, Any] | None:
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT *
            FROM reminder_record
            WHERE id = ?
            """,
            (reminder_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    return dict(row) if row else None


def _record_exists(
    table_name: str,
    reminder: dict[str, Any],
) -> bool:
    allowed_tables = {
        "confirm_record",
        "escalation_record",
        "recovery_record",
    }

    if table_name not in allowed_tables:
        raise ValueError("不允许查询的数据表")

    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {table_name}
            WHERE reminder_id = ?
               OR (
                   reminder_id IS NULL
                   AND trace_id = ?
                   AND item_id = ?
               )
            """,
            (
                reminder["id"],
                reminder["trace_id"],
                reminder["item_id"],
            ),
        )
        return cur.fetchone()[0] > 0
    finally:
        conn.close()


def _base_check(
    reminder_id: int,
    trace_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    reminder = get_reminder_by_id(reminder_id)

    if reminder is None:
        return None, {
            "outcome": "not_found",
            "business_status": "无法办理",
            "message": "提醒记录不存在",
            "reminder_id": reminder_id,
        }

    if reminder["trace_id"] != trace_id:
        return None, {
            "outcome": "trace_mismatch",
            "business_status": "无法办理",
            "message": "请求 trace_id 与提醒记录不一致",
            "reminder_id": reminder_id,
            "registered_trace_id": reminder["trace_id"],
        }

    if reminder["status"] == "已抑制":
        return None, {
            "outcome": "invalid_state",
            "business_status": "无法办理",
            "message": "抑制记录不允许执行确认、升级或恢复操作",
            "reminder_id": reminder_id,
        }

    return reminder, None


def confirm_reminder(
    reminder_id: int,
    request_data: dict[str, Any],
) -> dict[str, Any]:
    reminder, error = _base_check(
        reminder_id,
        request_data["trace_id"],
    )
    if error:
        return error

    assert reminder is not None

    if _record_exists("recovery_record", reminder):
        return {
            "outcome": "invalid_state",
            "business_status": "无法办理",
            "message": "该提醒已经恢复销记，不能再次确认",
            "reminder_id": reminder_id,
            "item_id": reminder["item_id"],
        }

    if _record_exists("confirm_record", reminder):
        return {
            "outcome": "already_confirmed",
            "business_status": "已完成",
            "message": "该提醒已经完成真人确认，本次不重复写入",
            "reminder_id": reminder_id,
            "item_id": reminder["item_id"],
        }

    result = simulate_confirm(
        trace_id=reminder["trace_id"],
        item_id=reminder["item_id"],
        user=request_data["confirm_user"],
        reminder_id=reminder_id,
    )

    return {
        "outcome": "confirmed",
        "business_status": result.get("status", "已完成"),
        "message": result.get("message", "真人确认完成"),
        "reminder_id": reminder_id,
        "item_id": reminder["item_id"],
        "confirm_user": request_data["confirm_user"],
        "service_result": result,
    }


def recover_reminder(
    reminder_id: int,
    request_data: dict[str, Any],
) -> dict[str, Any]:
    reminder, error = _base_check(
        reminder_id,
        request_data["trace_id"],
    )
    if error:
        return error

    assert reminder is not None

    if _record_exists("recovery_record", reminder):
        return {
            "outcome": "already_recovered",
            "business_status": "已完成",
            "message": "该提醒已经恢复销记，本次不重复写入",
            "reminder_id": reminder_id,
            "item_id": reminder["item_id"],
        }

    if not _record_exists("confirm_record", reminder):
        return {
            "outcome": "invalid_state",
            "business_status": "无法办理",
            "message": "提醒尚未完成真人确认，不能恢复销记",
            "reminder_id": reminder_id,
            "item_id": reminder["item_id"],
        }

    result = simulate_recovery(
        trace_id=reminder["trace_id"],
        item_id=reminder["item_id"],
        user=request_data["recovery_user"],
        reminder_id=reminder_id,
    )

    return {
        "outcome": "recovered",
        "business_status": result.get("status", "已完成"),
        "message": result.get("message", "恢复销记完成"),
        "reminder_id": reminder_id,
        "item_id": reminder["item_id"],
        "recovery_user": request_data["recovery_user"],
        "service_result": result,
    }


def escalate_reminder(
    reminder_id: int,
    request_data: dict[str, Any],
) -> dict[str, Any]:
    reminder, error = _base_check(
        reminder_id,
        request_data["trace_id"],
    )
    if error:
        return error

    assert reminder is not None

    if _record_exists("recovery_record", reminder):
        return {
            "outcome": "invalid_state",
            "business_status": "无法办理",
            "message": "该提醒已经恢复销记，不能升级催办",
            "reminder_id": reminder_id,
            "item_id": reminder["item_id"],
        }

    if _record_exists("confirm_record", reminder):
        return {
            "outcome": "invalid_state",
            "business_status": "无法办理",
            "message": "该提醒已经确认，不能升级催办",
            "reminder_id": reminder_id,
            "item_id": reminder["item_id"],
        }

    if _record_exists("escalation_record", reminder):
        return {
            "outcome": "already_escalated",
            "business_status": "待真人确认",
            "message": "该提醒已经生成升级催办记录",
            "reminder_id": reminder_id,
            "item_id": reminder["item_id"],
        }

    result = simulate_escalation(
        trace_id=reminder["trace_id"],
        item_id=reminder["item_id"],
        escalation_role=request_data["escalation_role"],
        reason=request_data["reason"],
        reminder_id=reminder_id,
    )

    return {
        "outcome": "escalated",
        "business_status": result.get("status", "待真人确认"),
        "message": result.get("message", "升级催办完成"),
        "reminder_id": reminder_id,
        "item_id": reminder["item_id"],
        "escalation_role": request_data["escalation_role"],
        "reason": request_data["reason"],
        "service_result": result,
    }
