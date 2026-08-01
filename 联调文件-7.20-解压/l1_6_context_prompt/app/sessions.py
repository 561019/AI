from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

from .audit import write_audit_event
from .db import connect, row_to_dict, rows_to_dicts
from .permissions import check_permission
from .utils import ApiError, new_id, now_iso, require_fields


WARNING_RATIO = 0.80
HANDOFF_RATIO = 0.85
LOCK_RATIO = 1.0


def create_session(payload: dict[str, Any]) -> dict[str, Any]:
    require_fields(payload, ["project_id", "title", "capacity_limit", "created_by"])
    actor_id = payload["created_by"]
    check_permission(
        actor_id=actor_id,
        action="create",
        resource_type="conversation_session",
        scope_level="project",
        scope_id=payload["project_id"],
    )
    capacity_limit = int(payload["capacity_limit"])
    if capacity_limit <= 0:
        raise ApiError(HTTPStatus.BAD_REQUEST, "capacity_limit must be greater than 0")
    now = now_iso()
    item = {
        "id": new_id("sess"),
        "tenant_id": payload.get("tenant_id", "default"),
        "project_id": payload["project_id"],
        "title": payload["title"],
        "capacity_limit": capacity_limit,
        "used_units": int(payload.get("used_units", 0)),
        "capacity_ratio": 0,
        "status": "active",
        "summary": payload.get("summary"),
        "open_todos": _json_text(payload.get("open_todos", [])),
        "decisions": _json_text(payload.get("decisions", [])),
        "risks": _json_text(payload.get("risks", [])),
        "auto_handoff_done": 0,
        "locked": 0,
        "next_session_id": None,
        "created_by": actor_id,
        "updated_by": actor_id,
        "created_at": now,
        "updated_at": now,
    }
    item["capacity_ratio"] = _ratio(item["used_units"], item["capacity_limit"])
    item["status"] = _status_for_ratio(item["capacity_ratio"])
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO conversation_session (
              id, tenant_id, project_id, title, capacity_limit, used_units,
              capacity_ratio, status, summary, open_todos, decisions, risks,
              auto_handoff_done, locked, next_session_id,
              created_by, updated_by, created_at, updated_at
            ) VALUES (
              :id, :tenant_id, :project_id, :title, :capacity_limit, :used_units,
              :capacity_ratio, :status, :summary, :open_todos, :decisions, :risks,
              :auto_handoff_done, :locked, :next_session_id,
              :created_by, :updated_by, :created_at, :updated_at
            )
            """,
            item,
        )
    _record_capacity_event_if_needed(item)
    write_audit_event(
        actor_id=actor_id,
        action="session.create",
        resource_type="conversation_session",
        resource_id=item["id"],
        scope_level="project",
        scope_id=item["project_id"],
    )
    return _decode_session(item)


def list_sessions(query: dict[str, list[str]], actor_id: str) -> list[dict[str, Any]]:
    project_id = _first(query, "project_id")
    status = _first(query, "status")
    include_deleted = _first(query, "include_deleted") in {"1", "true", "yes"}
    check_permission(
        actor_id=actor_id,
        action="read",
        resource_type="conversation_session",
        scope_level="project",
        scope_id=project_id,
    )
    clauses = ["1 = 1"]
    params: list[Any] = []
    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    elif not include_deleted:
        clauses.append("status != 'deleted'")
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM conversation_session WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT 100",
            params,
        ).fetchall()
    return [_decode_session(row) for row in rows_to_dicts(rows)]


def get_session(session_id: str, actor_id: str) -> dict[str, Any]:
    item = _get_session_raw(session_id)
    check_permission(
        actor_id=actor_id,
        action="read",
        resource_type="conversation_session",
        resource_id=session_id,
        scope_level="project",
        scope_id=item["project_id"],
    )
    return _decode_session(item)


def delete_session(session_id: str, actor_id: str) -> dict[str, Any]:
    item = _get_session_raw(session_id)
    check_permission(
        actor_id=actor_id,
        action="delete",
        resource_type="conversation_session",
        resource_id=session_id,
        scope_level="project",
        scope_id=item["project_id"],
    )
    with connect() as conn:
        conn.execute(
            """
            UPDATE conversation_session
            SET status = 'deleted', updated_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (actor_id, now_iso(), session_id),
        )
    write_audit_event(
        actor_id=actor_id,
        action="session.delete",
        resource_type="conversation_session",
        resource_id=session_id,
        scope_level="project",
        scope_id=item["project_id"],
    )
    return _decode_session(_get_session_raw(session_id))


def update_session_capacity(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("updated_by")
    if not actor_id:
        raise ApiError(HTTPStatus.BAD_REQUEST, "actor_id or updated_by is required")
    item = _get_session_raw(session_id)
    check_permission(
        actor_id=actor_id,
        action="update_capacity",
        resource_type="conversation_session",
        resource_id=session_id,
        scope_level="project",
        scope_id=item["project_id"],
    )
    used_units = int(payload.get("used_units", item["used_units"]))
    if "delta_units" in payload:
        used_units = int(item["used_units"]) + int(payload["delta_units"])
    if used_units < 0:
        raise ApiError(HTTPStatus.BAD_REQUEST, "used_units cannot be negative")
    capacity_ratio = _ratio(used_units, int(item["capacity_limit"]))
    status = _status_for_ratio(capacity_ratio)
    updates = {
        "used_units": used_units,
        "capacity_ratio": capacity_ratio,
        "status": status,
        "updated_by": actor_id,
        "updated_at": now_iso(),
        "id": session_id,
    }
    with connect() as conn:
        conn.execute(
            """
            UPDATE conversation_session
            SET used_units = :used_units, capacity_ratio = :capacity_ratio,
                status = :status, updated_by = :updated_by, updated_at = :updated_at
            WHERE id = :id
            """,
            updates,
        )
    updated = _get_session_raw(session_id)
    _record_capacity_event_if_needed(updated)
    if updated["capacity_ratio"] >= LOCK_RATIO and not updated.get("locked"):
        lock_session(session_id, actor_id)
        updated = _get_session_raw(session_id)
    write_audit_event(
        actor_id=actor_id,
        action="session.capacity_update",
        resource_type="conversation_session",
        resource_id=session_id,
        scope_level="project",
        scope_id=updated["project_id"],
        detail={"capacity_ratio": capacity_ratio, "status": status},
    )
    return _decode_session(updated)


def update_session_notes(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("updated_by")
    if not actor_id:
        raise ApiError(HTTPStatus.BAD_REQUEST, "actor_id or updated_by is required")
    item = _get_session_raw(session_id)
    check_permission(
        actor_id=actor_id,
        action="update_notes",
        resource_type="conversation_session",
        resource_id=session_id,
        scope_level="project",
        scope_id=item["project_id"],
    )
    allowed = ["title", "summary", "open_todos", "decisions", "risks"]
    updates = {field: payload[field] for field in allowed if field in payload}
    if not updates:
        return _decode_session(item)
    for field in ["open_todos", "decisions", "risks"]:
        if field in updates:
            updates[field] = _json_text(updates[field])
    updates["updated_by"] = actor_id
    updates["updated_at"] = now_iso()
    updates["id"] = session_id
    assignments = ", ".join([f"{field} = :{field}" for field in updates if field != "id"])
    with connect() as conn:
        conn.execute(f"UPDATE conversation_session SET {assignments} WHERE id = :id", updates)
    return _decode_session(_get_session_raw(session_id))


def list_capacity_events(session_id: str, actor_id: str) -> list[dict[str, Any]]:
    item = _get_session_raw(session_id)
    check_permission(
        actor_id=actor_id,
        action="read_events",
        resource_type="conversation_session",
        resource_id=session_id,
        scope_level="project",
        scope_id=item["project_id"],
    )
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM capacity_event WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
    return rows_to_dicts(rows)


def lock_session(session_id: str, actor_id: str) -> dict[str, Any]:
    """将 session 的 locked 字段设为 1，status 设为 'locked'"""
    item = _get_session_raw(session_id)
    check_permission(
        actor_id=actor_id,
        action="lock",
        resource_type="conversation_session",
        resource_id=session_id,
        scope_level="project",
        scope_id=item["project_id"],
    )
    with connect() as conn:
        conn.execute(
            "UPDATE conversation_session SET locked = 1, status = 'locked', updated_at = ? WHERE id = ?",
            (now_iso(), session_id),
        )
    write_audit_event(
        actor_id=actor_id,
        action="session.lock",
        resource_type="conversation_session",
        resource_id=session_id,
        scope_level="project",
        scope_id=item["project_id"],
        detail={"capacity_ratio": item["capacity_ratio"]},
    )
    return _decode_session(_get_session_raw(session_id))


def mark_auto_handoff_done(session_id: str, next_session_id: str, actor_id: str) -> dict[str, Any]:
    """标记 auto_handoff_done=1，记录 next_session_id"""
    item = _get_session_raw(session_id)
    check_permission(
        actor_id=actor_id,
        action="mark_handoff",
        resource_type="conversation_session",
        resource_id=session_id,
        scope_level="project",
        scope_id=item["project_id"],
    )
    with connect() as conn:
        conn.execute(
            """UPDATE conversation_session
               SET auto_handoff_done = 1, next_session_id = ?, updated_at = ?
               WHERE id = ?""",
            (next_session_id, now_iso(), session_id),
        )
    write_audit_event(
        actor_id=actor_id,
        action="session.auto_handoff_done",
        resource_type="conversation_session",
        resource_id=session_id,
        scope_level="project",
        scope_id=item["project_id"],
        detail={"next_session_id": next_session_id},
    )
    return _decode_session(_get_session_raw(session_id))


def check_session_writable(session_id: str, actor_id: str) -> dict[str, Any]:
    """检查 session 是否可写：locked 则抛出 423 Locked；否则返回 session"""
    session = get_session(session_id, actor_id)
    if session.get("locked"):
        raise ApiError(HTTPStatus.LOCKED, "该对话框已超过 100% 容量，已锁定。只能翻阅历史记录。")
    return session


def _record_capacity_event_if_needed(item: dict[str, Any]) -> None:
    event_type = None
    message = None
    if item["capacity_ratio"] >= HANDOFF_RATIO:
        event_type = "force_handoff"
        message = "容量达到 85%，必须生成工作汇报文件和工作交接文件后收口。"
    elif item["capacity_ratio"] >= WARNING_RATIO:
        event_type = "warning_80"
        message = "容量达到 80%，建议开始收口并准备交接。"
    if not event_type:
        return
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM capacity_event WHERE session_id = ? AND event_type = ?",
            (item["id"], event_type),
        ).fetchone()
        if existing:
            return
        conn.execute(
            """
            INSERT INTO capacity_event (id, session_id, event_type, capacity_ratio, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (new_id("cap"), item["id"], event_type, item["capacity_ratio"], message, now_iso()),
        )


def _get_session_raw(session_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM conversation_session WHERE id = ?", (session_id,)).fetchone()
    item = row_to_dict(row)
    if not item:
        raise ApiError(HTTPStatus.NOT_FOUND, "Conversation session not found")
    return item


def _decode_session(item: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(item)
    for field in ["open_todos", "decisions", "risks"]:
        decoded[field] = json.loads(decoded[field] or "[]")
    decoded["auto_handoff_done"] = bool(decoded.get("auto_handoff_done"))
    decoded["locked"] = bool(decoded.get("locked"))
    return decoded


def _json_text(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _ratio(used_units: int, capacity_limit: int) -> float:
    return round(min(used_units / capacity_limit, 1.0), 4)


def _status_for_ratio(capacity_ratio: float) -> str:
    if capacity_ratio >= LOCK_RATIO:
        return "locked"
    if capacity_ratio >= HANDOFF_RATIO:
        return "handoff_required"
    if capacity_ratio >= WARNING_RATIO:
        return "warning"
    return "active"


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]
