from __future__ import annotations

from http import HTTPStatus
from typing import Any

from .audit import write_audit_event
from .db import connect, row_to_dict, rows_to_dicts
from .permissions import check_permission
from .utils import ApiError, new_id, now_iso, require_fields


CREATE_FIELDS = [
    "scope_level",
    "scope_id",
    "context_type",
    "title",
    "summary",
    "created_by",
]


def create_context_memory(payload: dict[str, Any]) -> dict[str, Any]:
    require_fields(payload, CREATE_FIELDS)
    actor_id = payload["created_by"]
    check_permission(
        actor_id=actor_id,
        action="create",
        resource_type="context_memory",
        scope_level=payload["scope_level"],
        scope_id=payload["scope_id"],
    )
    now = now_iso()
    item = {
        "id": new_id("ctx"),
        "tenant_id": payload.get("tenant_id", "default"),
        "scope_level": payload["scope_level"],
        "scope_id": payload["scope_id"],
        "context_type": payload["context_type"],
        "title": payload["title"],
        "summary": payload["summary"],
        "content": payload.get("content"),
        "content_ref": payload.get("content_ref"),
        "memory_engine_ref": payload.get("memory_engine_ref"),
        "source_type": payload.get("source_type"),
        "source_id": payload.get("source_id"),
        "confidence": float(payload.get("confidence", 1.0)),
        "status": "active",
        "created_by": actor_id,
        "updated_by": actor_id,
        "expires_at": payload.get("expires_at"),
        "created_at": now,
        "updated_at": now,
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO context_memory (
              id, tenant_id, scope_level, scope_id, context_type, title, summary,
              content, content_ref, memory_engine_ref, source_type, source_id,
              confidence, status, created_by, updated_by, expires_at, created_at, updated_at
            ) VALUES (
              :id, :tenant_id, :scope_level, :scope_id, :context_type, :title, :summary,
              :content, :content_ref, :memory_engine_ref, :source_type, :source_id,
              :confidence, :status, :created_by, :updated_by, :expires_at, :created_at, :updated_at
            )
            """,
            item,
        )
    write_audit_event(
        actor_id=actor_id,
        action="context_memory.create",
        resource_type="context_memory",
        resource_id=item["id"],
        scope_level=item["scope_level"],
        scope_id=item["scope_id"],
    )
    return item


def list_context_memories(query: dict[str, list[str]], actor_id: str) -> list[dict[str, Any]]:
    scope_level = _first(query, "scope_level")
    scope_id = _first(query, "scope_id")
    context_type = _first(query, "context_type")
    search = _first(query, "q")
    status = _first(query, "status") or "active"

    check_permission(
        actor_id=actor_id,
        action="read",
        resource_type="context_memory",
        scope_level=scope_level,
        scope_id=scope_id,
    )

    clauses = ["status = ?"]
    params: list[Any] = [status]
    if scope_level:
        clauses.append("scope_level = ?")
        params.append(scope_level)
    if scope_id:
        clauses.append("scope_id = ?")
        params.append(scope_id)
    if context_type:
        clauses.append("context_type = ?")
        params.append(context_type)
    if search:
        clauses.append("(title LIKE ? OR summary LIKE ? OR content LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])

    sql = f"""
      SELECT * FROM context_memory
      WHERE {' AND '.join(clauses)}
      ORDER BY updated_at DESC
      LIMIT 100
    """
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    write_audit_event(
        actor_id=actor_id,
        action="context_memory.list",
        resource_type="context_memory",
        scope_level=scope_level,
        scope_id=scope_id,
        detail={"count": len(rows)},
    )
    return rows_to_dicts(rows)


def get_context_memory(item_id: str, actor_id: str) -> dict[str, Any]:
    item = _get(item_id)
    check_permission(
        actor_id=actor_id,
        action="read",
        resource_type="context_memory",
        resource_id=item_id,
        scope_level=item["scope_level"],
        scope_id=item["scope_id"],
    )
    write_audit_event(
        actor_id=actor_id,
        action="context_memory.get",
        resource_type="context_memory",
        resource_id=item_id,
        scope_level=item["scope_level"],
        scope_id=item["scope_id"],
    )
    return item


def update_context_memory(item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    item = _get(item_id)
    actor_id = payload.get("updated_by") or payload.get("actor_id")
    if not actor_id:
        raise ApiError(HTTPStatus.BAD_REQUEST, "updated_by or actor_id is required")
    check_permission(
        actor_id=actor_id,
        action="update",
        resource_type="context_memory",
        resource_id=item_id,
        scope_level=item["scope_level"],
        scope_id=item["scope_id"],
    )
    allowed_fields = [
        "context_type",
        "title",
        "summary",
        "content",
        "content_ref",
        "memory_engine_ref",
        "confidence",
        "expires_at",
    ]
    updates = {field: payload[field] for field in allowed_fields if field in payload}
    if not updates:
        return item
    updates["updated_by"] = actor_id
    updates["updated_at"] = now_iso()
    assignments = ", ".join([f"{field} = :{field}" for field in updates])
    updates["id"] = item_id
    with connect() as conn:
        conn.execute(f"UPDATE context_memory SET {assignments} WHERE id = :id", updates)
    updated = _get(item_id)
    write_audit_event(
        actor_id=actor_id,
        action="context_memory.update",
        resource_type="context_memory",
        resource_id=item_id,
        scope_level=updated["scope_level"],
        scope_id=updated["scope_id"],
        detail={"fields": list(updates.keys())},
    )
    return updated


def archive_context_memory(item_id: str, actor_id: str) -> dict[str, Any]:
    item = _get(item_id)
    check_permission(
        actor_id=actor_id,
        action="archive",
        resource_type="context_memory",
        resource_id=item_id,
        scope_level=item["scope_level"],
        scope_id=item["scope_id"],
    )
    with connect() as conn:
        conn.execute(
            """
            UPDATE context_memory
            SET status = 'archived', updated_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (actor_id, now_iso(), item_id),
        )
    updated = _get(item_id)
    write_audit_event(
        actor_id=actor_id,
        action="context_memory.archive",
        resource_type="context_memory",
        resource_id=item_id,
        scope_level=updated["scope_level"],
        scope_id=updated["scope_id"],
    )
    return updated


def _get(item_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM context_memory WHERE id = ?", (item_id,)).fetchone()
    item = row_to_dict(row)
    if not item:
        raise ApiError(HTTPStatus.NOT_FOUND, "Context memory not found")
    return item


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]

