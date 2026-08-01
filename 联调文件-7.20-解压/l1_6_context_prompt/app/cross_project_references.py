from __future__ import annotations

from http import HTTPStatus
from typing import Any

from .audit import write_audit_event
from .db import connect, row_to_dict, rows_to_dicts
from .permissions import check_permission
from .utils import ApiError, new_id, now_iso


def create_cross_project_reference(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("created_by") or "system"
    check_permission(
        actor_id=actor_id,
        action="create",
        resource_type="cross_project_reference",
        scope_level="project",
        scope_id=project_id,
    )
    source_project_id = str(payload.get("source_project_id") or "").strip()
    source_record_type = str(payload.get("source_record_type") or payload.get("kind") or "").strip()
    source_record_id = str(payload.get("source_record_id") or payload.get("record_id") or "").strip()
    source_name = str(payload.get("source_name") or payload.get("name") or source_record_type or "跨项目引用").strip()
    if not source_project_id or not source_record_type or not source_record_id:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "source_project_id, source_record_type and source_record_id are required",
        )
    if source_project_id == project_id:
        raise ApiError(HTTPStatus.BAD_REQUEST, "不能把同一项目内容作为跨项目引用")
    item = {
        "id": new_id("xref"),
        "target_project_id": project_id,
        "source_project_id": source_project_id,
        "source_session_id": payload.get("source_session_id") or payload.get("session_id"),
        "source_record_type": source_record_type,
        "source_record_id": source_record_id,
        "source_name": source_name,
        "source_excerpt": _excerpt(payload.get("source_excerpt") or payload.get("content") or ""),
        "note": payload.get("note"),
        "status": "active",
        "created_by": actor_id,
        "created_at": now_iso(),
    }
    with connect() as conn:
        existing = row_to_dict(
            conn.execute(
                """
                SELECT * FROM cross_project_reference
                WHERE target_project_id = ?
                  AND source_project_id = ?
                  AND source_record_id = ?
                  AND status != 'deleted'
                LIMIT 1
                """,
                (project_id, source_project_id, source_record_id),
            ).fetchone()
        )
        if existing:
            return existing
        conn.execute(
            """
            INSERT INTO cross_project_reference (
              id, target_project_id, source_project_id, source_session_id,
              source_record_type, source_record_id, source_name, source_excerpt,
              note, status, created_by, created_at
            ) VALUES (
              :id, :target_project_id, :source_project_id, :source_session_id,
              :source_record_type, :source_record_id, :source_name, :source_excerpt,
              :note, :status, :created_by, :created_at
            )
            """,
            item,
        )
    write_audit_event(
        actor_id=actor_id,
        action="cross_project_reference.create",
        resource_type="cross_project_reference",
        resource_id=item["id"],
        scope_level="project",
        scope_id=project_id,
        detail={
            "source_project_id": source_project_id,
            "source_record_type": source_record_type,
            "source_record_id": source_record_id,
        },
    )
    return item


def list_cross_project_references(project_id: str, actor_id: str) -> list[dict[str, Any]]:
    check_permission(
        actor_id=actor_id,
        action="read",
        resource_type="cross_project_reference",
        scope_level="project",
        scope_id=project_id,
    )
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM cross_project_reference
            WHERE target_project_id = ? AND status != 'deleted'
            ORDER BY created_at DESC
            LIMIT 200
            """,
            (project_id,),
        ).fetchall()
    return rows_to_dicts(rows)


def check_existing_references(
    source_project_id: str, source_record_type: str, source_record_id: str, actor_id: str
) -> list[str]:
    """返回已引用此来源的所有 target_project_id 列表。"""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT target_project_id FROM cross_project_reference
            WHERE source_project_id = ?
              AND source_record_type = ?
              AND source_record_id = ?
              AND status != 'deleted'
            """,
            (source_project_id, source_record_type, source_record_id),
        ).fetchall()
    return [row["target_project_id"] for row in rows]


def delete_cross_project_reference(project_id: str, reference_id: str, actor_id: str) -> dict[str, Any]:
    check_permission(
        actor_id=actor_id,
        action="delete",
        resource_type="cross_project_reference",
        resource_id=reference_id,
        scope_level="project",
        scope_id=project_id,
    )
    with connect() as conn:
        item = row_to_dict(
            conn.execute(
                """
                SELECT * FROM cross_project_reference
                WHERE id = ? AND target_project_id = ?
                """,
                (reference_id, project_id),
            ).fetchone()
        )
        if not item:
            raise ApiError(HTTPStatus.NOT_FOUND, "Cross-project reference not found")
        conn.execute(
            """
            UPDATE cross_project_reference
            SET status = 'deleted'
            WHERE id = ? AND target_project_id = ?
            """,
            (reference_id, project_id),
        )
    write_audit_event(
        actor_id=actor_id,
        action="cross_project_reference.delete",
        resource_type="cross_project_reference",
        resource_id=reference_id,
        scope_level="project",
        scope_id=project_id,
    )
    deleted = dict(item)
    deleted["status"] = "deleted"
    return deleted


def _excerpt(value: Any) -> str:
    text = str(value or "").strip()
    return text[:2000] if text else "无摘要"
