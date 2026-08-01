from __future__ import annotations

import json
from typing import Any

from .db import connect
from .utils import new_id, now_iso


def write_audit_event(
    *,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    scope_level: str | None = None,
    scope_id: str | None = None,
    permission_result: str = "allow",
    trace_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "id": new_id("audit"),
        "actor_id": actor_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "scope_level": scope_level,
        "scope_id": scope_id,
        "permission_result": permission_result,
        "trace_id": trace_id,
        "detail": json.dumps(detail or {}, ensure_ascii=False),
        "created_at": now_iso(),
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_event (
              id, actor_id, action, resource_type, resource_id, scope_level,
              scope_id, permission_result, trace_id, detail, created_at
            ) VALUES (
              :id, :actor_id, :action, :resource_type, :resource_id, :scope_level,
              :scope_id, :permission_result, :trace_id, :detail, :created_at
            )
            """,
            event,
        )
    return event

