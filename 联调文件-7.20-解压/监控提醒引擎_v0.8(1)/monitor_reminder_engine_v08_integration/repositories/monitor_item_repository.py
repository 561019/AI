from __future__ import annotations

from datetime import datetime
from typing import Any

from db import get_conn


MONITOR_ITEM_COLUMNS = (
    "item_id",
    "trace_id",
    "object_type",
    "object_id",
    "rule_id",
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
    "status",
    "created_at",
    "updated_at",
)

UPDATABLE_FIELDS = {
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


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row)


def get_monitor_item(
    item_id: str,
) -> dict[str, Any] | None:
    conn = get_conn()

    try:
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
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_monitor_items(
    status: str = "",
    keyword: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    conditions: list[str] = []
    params: list[Any] = []

    if status:
        conditions.append("status = ?")
        params.append(status)

    if keyword:
        like_value = f"%{keyword}%"
        conditions.append(
            """
            (
                item_id LIKE ?
                OR trace_id LIKE ?
                OR object_id LIKE ?
                OR rule_id LIKE ?
                OR receiver_role LIKE ?
                OR notice_type LIKE ?
            )
            """
        )
        params.extend([like_value] * 6)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    conn = get_conn()

    try:
        cur = conn.cursor()

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM monitor_item
            {where_clause}
            """,
            params,
        )
        total = cur.fetchone()[0]

        cur.execute(
            f"""
            SELECT *
            FROM monitor_item
            {where_clause}
            ORDER BY created_at DESC, item_id ASC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        )

        items = [_row_to_dict(row) for row in cur.fetchall()]

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }
    finally:
        conn.close()


def update_monitor_item(
    item_id: str,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    filtered_updates = {
        key: value
        for key, value in updates.items()
        if key in UPDATABLE_FIELDS
    }

    if not filtered_updates:
        return get_monitor_item(item_id)

    filtered_updates["updated_at"] = datetime.now().isoformat(
        timespec="seconds"
    )

    set_clause = ", ".join(
        f"{field} = ?" for field in filtered_updates
    )

    conn = get_conn()

    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE monitor_item
            SET {set_clause}
            WHERE item_id = ?
            """,
            [*filtered_updates.values(), item_id],
        )
        conn.commit()

        if cur.rowcount == 0:
            return None
    finally:
        conn.close()

    return get_monitor_item(item_id)


def set_monitor_item_status(
    item_id: str,
    status: str,
) -> dict[str, Any] | None:
    conn = get_conn()

    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE monitor_item
            SET status = ?, updated_at = ?
            WHERE item_id = ?
            """,
            (
                status,
                datetime.now().isoformat(timespec="seconds"),
                item_id,
            ),
        )
        conn.commit()

        if cur.rowcount == 0:
            return None
    finally:
        conn.close()

    return get_monitor_item(item_id)
