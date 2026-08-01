from __future__ import annotations

import json
from typing import Any

from .db import connect, rows_to_dicts
from .permissions import check_permission
from .utils import new_id, now_iso


def create_control_center_message(
    *,
    scope_level: str,
    scope_id: str,
    role: str,
    content: str,
    actor_id: str,
    meta: str | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    check_permission(
        actor_id=actor_id,
        action="create",
        resource_type="control_center_message",
        scope_level=scope_level,
        scope_id=scope_id,
    )
    item = {
        "id": new_id("ccmsg"),
        "scope_level": scope_level,
        "scope_id": scope_id,
        "role": role,
        "content": content,
        "meta": meta,
        "result_json": json.dumps(result, ensure_ascii=False) if result is not None else None,
        "status": "active",
        "created_by": actor_id,
        "created_at": now_iso(),
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO control_center_message (
              id, scope_level, scope_id, role, content, meta,
              result_json, status, created_by, created_at
            ) VALUES (
              :id, :scope_level, :scope_id, :role, :content, :meta,
              :result_json, :status, :created_by, :created_at
            )
            """,
            item,
        )
    return item


def list_control_center_messages(
    *,
    scope_level: str,
    scope_id: str,
    actor_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    check_permission(
        actor_id=actor_id,
        action="read",
        resource_type="control_center_message",
        scope_level=scope_level,
        scope_id=scope_id,
    )
    limit = max(1, min(int(limit), 300))
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM control_center_message
            WHERE scope_level = ? AND scope_id = ? AND status != 'deleted'
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (scope_level, scope_id, limit),
        ).fetchall()
    return rows_to_dicts(rows)
