from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from db import get_conn
from repositories.governance_policy_repository import (
    resolve_dnd_policy,
    resolve_escalation_policy,
)


DEFAULT_TIMEZONE = "Asia/Shanghai"
URGENT_LEVELS = {"critical", "urgent", "emergency"}


def _parse_datetime(value: Any, timezone_name: str = DEFAULT_TIMEZONE) -> datetime:
    zone = ZoneInfo(timezone_name)
    if isinstance(value, str) and value.strip():
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=zone)
            return parsed.astimezone(zone)
        except ValueError:
            pass
    return datetime.now(zone)


def _parse_hhmm(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def _inside_dnd(current: datetime, start_text: str, end_text: str) -> bool:
    start = _parse_hhmm(start_text)
    end = _parse_hhmm(end_text)
    current_time = current.timetz().replace(tzinfo=None)

    if start == end:
        return False
    if start < end:
        return start <= current_time < end
    return current_time >= start or current_time < end


def _next_dnd_end(
    current: datetime,
    start_text: str,
    end_text: str,
) -> datetime:
    start = _parse_hhmm(start_text)
    end = _parse_hhmm(end_text)
    current_time = current.timetz().replace(tzinfo=None)
    end_today = current.replace(
        hour=end.hour,
        minute=end.minute,
        second=0,
        microsecond=0,
    )

    if start < end:
        return end_today if current_time < end else end_today + timedelta(days=1)

    # 跨夜时段，例如 22:00-08:00。
    if current_time >= start:
        return end_today + timedelta(days=1)
    return end_today


def _row_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row else None


def _event_id(judgement: dict[str, Any]) -> str:
    for field in ("event_id", "source_event_id", "operation_id"):
        value = judgement.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _find_duplicate_event(
    item_id: str,
    event_id: str,
) -> dict[str, Any] | None:
    if not event_id:
        return None

    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT *
            FROM reminder_record
            WHERE item_id = ? AND event_id = ?
              AND COALESCE(governance_action, 'send')
                  IN ('send', 'urgent_exception_send')
            ORDER BY id DESC
            LIMIT 1
            """,
            (item_id, event_id),
        ).fetchone()
        return _row_dict(row)
    finally:
        conn.close()


def _find_open_item_reminder(
    item_id: str,
) -> dict[str, Any] | None:
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT reminder.*
            FROM reminder_record AS reminder
            WHERE reminder.item_id = ?
              AND COALESCE(reminder.governance_action, 'send')
                  IN ('send', 'urgent_exception_send')
              AND reminder.status != '已抑制'
              AND NOT EXISTS (
                  SELECT 1
                  FROM recovery_record AS recovery
                  WHERE (
                      recovery.reminder_id = reminder.id
                      OR (
                          recovery.reminder_id IS NULL
                          AND recovery.trace_id = reminder.trace_id
                          AND recovery.item_id = reminder.item_id
                      )
                  )
              )
            ORDER BY reminder.id DESC
            LIMIT 1
            """,
            (item_id,),
        ).fetchone()
        return _row_dict(row)
    finally:
        conn.close()


def _find_merge_candidate(
    item: dict[str, Any],
    now: datetime,
) -> dict[str, Any] | None:
    merge_key = str(item.get("merge_key") or "").strip()
    merge_window = int(item.get("merge_window") or 0)
    if not merge_key or merge_window <= 0:
        return None

    cutoff = (now - timedelta(seconds=merge_window)).replace(
        tzinfo=None
    ).isoformat(timespec="seconds")

    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT reminder.*, monitor.merge_key
            FROM reminder_record AS reminder
            JOIN monitor_item AS monitor
              ON monitor.item_id = reminder.item_id
            WHERE monitor.merge_key = ?
              AND reminder.item_id != ?
              AND COALESCE(reminder.governance_action, 'send')
                  IN ('send', 'urgent_exception_send')
              AND reminder.created_at >= ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM recovery_record AS recovery
                  WHERE (
                      recovery.reminder_id = reminder.id
                      OR (
                          recovery.reminder_id IS NULL
                          AND recovery.trace_id = reminder.trace_id
                          AND recovery.item_id = reminder.item_id
                      )
                  )
              )
            ORDER BY reminder.id DESC
            LIMIT 1
            """,
            (merge_key, item["item_id"], cutoff),
        ).fetchone()
        return _row_dict(row)
    finally:
        conn.close()


def _find_latest_sent(
    item_id: str,
) -> dict[str, Any] | None:
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT *
            FROM reminder_record
            WHERE item_id = ?
              AND COALESCE(governance_action, 'send')
                  IN ('send', 'urgent_exception_send')
            ORDER BY id DESC
            LIMIT 1
            """,
            (item_id,),
        ).fetchone()
        return _row_dict(row)
    finally:
        conn.close()


def check_governance(
    item: dict[str, Any],
    judgement: dict[str, Any],
) -> dict[str, Any]:
    """
    按固定顺序执行确定性治理：
    精确事件去重 -> 未销记提醒去重 -> 同类合并 -> 重复间隔
    -> 免打扰 -> 紧急例外。
    """
    item_id = item["item_id"]
    event_id = _event_id(judgement)
    alert_level = str(item.get("alert_level") or "warning").lower()
    dnd_policy = resolve_dnd_policy(item.get("dnd_rule_ref") or "DND_NONE")
    escalation_policy = resolve_escalation_policy(
        item.get("escalation_rule_ref") or "ESC_NONE"
    )

    timezone_name = str(dnd_policy.get("timezone") or DEFAULT_TIMEZONE)
    event_time = _parse_datetime(
        judgement.get("event_time")
        or judgement.get("triggered_at")
        or judgement.get("occurred_at"),
        timezone_name,
    )
    now_for_db = datetime.now()

    duplicate = _find_duplicate_event(item_id, event_id)
    if duplicate:
        return {
            "allow_send": False,
            "decision": "duplicate_suppressed",
            "record_status": "已抑制",
            "governance_result": "相同事件编号已办理，本次不重复发送",
            "event_id": event_id,
            "related_reminder_id": duplicate["id"],
            "dnd_rule_ref": dnd_policy["rule_ref"],
            "escalation_rule_ref": escalation_policy["rule_ref"],
        }

    open_reminder = _find_open_item_reminder(item_id)
    if open_reminder:
        return {
            "allow_send": False,
            "decision": "open_alert_suppressed",
            "record_status": "已抑制",
            "governance_result": "存在尚未恢复销记的提醒，本次不重复打扰",
            "event_id": event_id,
            "related_reminder_id": open_reminder["id"],
            "dnd_rule_ref": dnd_policy["rule_ref"],
            "escalation_rule_ref": escalation_policy["rule_ref"],
        }

    merge_candidate = _find_merge_candidate(item, now_for_db)
    if merge_candidate:
        return {
            "allow_send": False,
            "decision": "merged",
            "record_status": "已合并",
            "governance_result": (
                "同类提醒处于合并窗口内，已合并到提醒 "
                f"{merge_candidate['id']}"
            ),
            "event_id": event_id,
            "merged_into_reminder_id": merge_candidate["id"],
            "related_reminder_id": merge_candidate["id"],
            "dnd_rule_ref": dnd_policy["rule_ref"],
            "escalation_rule_ref": escalation_policy["rule_ref"],
        }

    repeat_interval = int(item.get("repeat_interval") or 0)
    latest_sent = _find_latest_sent(item_id)
    if latest_sent and repeat_interval > 0:
        try:
            last_time = datetime.fromisoformat(latest_sent["created_at"])
        except (TypeError, ValueError):
            last_time = now_for_db - timedelta(seconds=repeat_interval + 1)
        elapsed = (now_for_db - last_time).total_seconds()
        if elapsed < repeat_interval:
            next_eligible = last_time + timedelta(seconds=repeat_interval)
            return {
                "allow_send": False,
                "decision": "repeat_interval_suppressed",
                "record_status": "已抑制",
                "governance_result": (
                    "重复提醒最小间隔尚未结束，"
                    f"还需等待 {max(0, int(repeat_interval - elapsed))} 秒"
                ),
                "event_id": event_id,
                "related_reminder_id": latest_sent["id"],
                "next_eligible_at": next_eligible.isoformat(
                    timespec="seconds"
                ),
                "dnd_rule_ref": dnd_policy["rule_ref"],
                "escalation_rule_ref": escalation_policy["rule_ref"],
            }

    urgent_override = bool(judgement.get("urgent_override"))
    exception_levels = {
        str(level).lower()
        for level in dnd_policy.get("exception_levels", [])
    }
    urgent_exception = (
        urgent_override
        or alert_level in URGENT_LEVELS
        or alert_level in exception_levels
    )

    if dnd_policy.get("enabled") and _inside_dnd(
        event_time,
        str(dnd_policy["start"]),
        str(dnd_policy["end"]),
    ):
        if not urgent_exception:
            next_eligible = _next_dnd_end(
                event_time,
                str(dnd_policy["start"]),
                str(dnd_policy["end"]),
            )
            return {
                "allow_send": False,
                "decision": "dnd_deferred",
                "record_status": "已暂缓",
                "governance_result": (
                    f"当前处于免打扰时段，按制度 "
                    f"{dnd_policy['rule_ref']} 暂缓发送"
                ),
                "event_id": event_id,
                "next_eligible_at": next_eligible.isoformat(
                    timespec="seconds"
                ),
                "dnd_rule_ref": dnd_policy["rule_ref"],
                "escalation_rule_ref": escalation_policy["rule_ref"],
            }

        return {
            "allow_send": True,
            "decision": "urgent_exception_send",
            "record_status": "待确认",
            "governance_result": (
                f"当前处于免打扰时段，但提醒级别 {alert_level} "
                "满足紧急例外，允许发送"
            ),
            "event_id": event_id,
            "urgent_exception": True,
            "dnd_rule_ref": dnd_policy["rule_ref"],
            "escalation_rule_ref": escalation_policy["rule_ref"],
        }

    return {
        "allow_send": True,
        "decision": "send",
        "record_status": "待确认",
        "governance_result": "治理检查通过，允许发送",
        "event_id": event_id,
        "urgent_exception": False,
        "dnd_rule_ref": dnd_policy["rule_ref"],
        "escalation_rule_ref": escalation_policy["rule_ref"],
    }
