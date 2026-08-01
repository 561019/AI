from __future__ import annotations

from http import HTTPStatus
from typing import Any

from .audit import write_audit_event
from .db import connect, row_to_dict, rows_to_dicts
from .permissions import check_permission
from .utils import ApiError, new_id, now_iso, require_fields


def create_artifact_file(payload: dict[str, Any]) -> dict[str, Any]:
    require_fields(payload, ["project_id", "artifact_type", "title", "summary", "storage_ref", "created_by"])
    actor_id = payload["created_by"]
    check_permission(
        actor_id=actor_id,
        action="create",
        resource_type="artifact_file",
        scope_level="project",
        scope_id=payload["project_id"],
    )
    item = {
        "id": new_id("file"),
        "tenant_id": payload.get("tenant_id", "default"),
        "project_id": payload["project_id"],
        "session_id": payload.get("session_id"),
        "artifact_type": payload["artifact_type"],
        "title": payload["title"],
        "summary": payload["summary"],
        "storage_ref": payload["storage_ref"],
        "download_ref": payload.get("download_ref"),
        "content": payload.get("content"),
        "created_by": actor_id,
        "created_at": now_iso(),
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO artifact_file (
              id, tenant_id, project_id, session_id, artifact_type, title, summary,
              storage_ref, download_ref, content, created_by, created_at
            ) VALUES (
              :id, :tenant_id, :project_id, :session_id, :artifact_type, :title, :summary,
              :storage_ref, :download_ref, :content, :created_by, :created_at
            )
            """,
            item,
        )
    write_audit_event(
        actor_id=actor_id,
        action="artifact_file.create",
        resource_type="artifact_file",
        resource_id=item["id"],
        scope_level="project",
        scope_id=item["project_id"],
    )
    return item


def list_artifact_files(query: dict[str, list[str]], actor_id: str) -> list[dict[str, Any]]:
    project_id = _first(query, "project_id")
    session_id = _first(query, "session_id")
    artifact_type = _first(query, "artifact_type")
    search = _first(query, "q")
    check_permission(
        actor_id=actor_id,
        action="read",
        resource_type="artifact_file",
        scope_level="project",
        scope_id=project_id,
    )
    clauses = ["1 = 1"]
    params: list[Any] = []
    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if artifact_type:
        clauses.append("artifact_type = ?")
        params.append(artifact_type)
    if search:
        clauses.append("(title LIKE ? OR summary LIKE ? OR content LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM artifact_file WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT 100",
            params,
        ).fetchall()
    return rows_to_dicts(rows)


def get_artifact_file(file_id: str, actor_id: str) -> dict[str, Any]:
    item = _get_artifact_raw(file_id)
    check_permission(
        actor_id=actor_id,
        action="read",
        resource_type="artifact_file",
        resource_id=file_id,
        scope_level="project",
        scope_id=item["project_id"],
    )
    return item


def _get_artifact_raw(file_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM artifact_file WHERE id = ?", (file_id,)).fetchone()
    item = row_to_dict(row)
    if not item:
        raise ApiError(HTTPStatus.NOT_FOUND, "Artifact file not found")
    return item


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]
