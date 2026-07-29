from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_conn


CORE_TABLES = [
    "monitor_item",
    "reminder_record",
    "delivery_record",
    "confirm_record",
    "escalation_record",
    "recovery_record",
    "workflow_callback_record",
]

AUDIT_TABLE = "api_request_record"

TABLES = [*CORE_TABLES, AUDIT_TABLE]


def database_exists() -> bool:
    return Path(DB_PATH).exists()


def database_connected() -> bool:
    try:
        conn = get_conn()
        conn.execute("SELECT 1")
        conn.close()
        return True
    except Exception:
        return False


def table_exists(table_name: str) -> bool:
    if table_name not in TABLES or not database_exists():
        return False

    conn = get_conn()

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def _event_matches(
    event: dict[str, Any],
    reminder: dict[str, Any],
) -> bool:
    event_reminder_id = event.get("reminder_id")
    if event_reminder_id is not None:
        return int(event_reminder_id) == int(reminder["id"])

    return (
        event.get("trace_id") == reminder.get("trace_id")
        and event.get("item_id") == reminder.get("item_id")
    )


def _append_derived_status(
    result: dict[str, list[dict[str, Any]]],
) -> None:
    confirms = result.get("confirm_record", [])
    escalations = result.get("escalation_record", [])
    recoveries = result.get("recovery_record", [])

    for reminder in result.get("reminder_record", []):
        governance_action = reminder.get("governance_action")
        stored_status = reminder.get("status")

        if governance_action == "merged" or stored_status == "已合并":
            current_status = "已合并"
        elif governance_action == "dnd_deferred" or stored_status == "已暂缓":
            current_status = "已暂缓"
        elif (
            governance_action in {
                "duplicate_suppressed",
                "open_alert_suppressed",
                "repeat_interval_suppressed",
                "suppressed",
            }
            or stored_status == "已抑制"
        ):
            current_status = "已抑制"
        elif any(_event_matches(row, reminder) for row in recoveries):
            current_status = "已恢复销记"
        elif any(_event_matches(row, reminder) for row in confirms):
            current_status = "已确认"
        elif any(_event_matches(row, reminder) for row in escalations):
            current_status = "已升级待确认"
        else:
            current_status = "待真人确认"

        reminder["current_status"] = current_status
        reminder["append_only"] = True


def read_trace_records(
    trace_id: str,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        table_name: [] for table_name in TABLES
    }

    if not database_exists():
        return result

    conn = get_conn()

    try:
        cur = conn.cursor()

        for table_name in TABLES:
            if not table_exists(table_name):
                continue

            cur.execute(f"PRAGMA table_info({table_name})")
            columns = [row[1] for row in cur.fetchall()]

            if "trace_id" not in columns:
                continue

            cur.execute(
                f"""
                SELECT *
                FROM {table_name}
                WHERE trace_id = ?
                ORDER BY rowid ASC
                """,
                (trace_id,),
            )

            result[table_name] = [
                dict(row) for row in cur.fetchall()
            ]
    finally:
        conn.close()

    _append_derived_status(result)
    return result
