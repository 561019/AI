from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

from .audit import write_audit_event
from .db import connect, row_to_dict, rows_to_dicts
from .langfuse_platform import bind_prompt_version_to_platform, list_prompt_platform_bindings
from .permissions import check_permission
from .utils import ApiError, new_id, now_iso, require_fields


def create_prompt_template(payload: dict[str, Any]) -> dict[str, Any]:
    require_fields(payload, ["prompt_code", "scope_level", "scope_id", "name", "owner_id"])
    actor_id = payload["owner_id"]
    check_permission(
        actor_id=actor_id,
        action="create",
        resource_type="prompt_template",
        scope_level=payload["scope_level"],
        scope_id=payload["scope_id"],
    )
    now = now_iso()
    item = {
        "id": new_id("pt"),
        "tenant_id": payload.get("tenant_id", "default"),
        "prompt_code": payload["prompt_code"],
        "scope_level": payload["scope_level"],
        "scope_id": payload["scope_id"],
        "name": payload["name"],
        "description": payload.get("description"),
        "status": "draft",
        "active_version_id": None,
        "owner_id": actor_id,
        "created_at": now,
        "updated_at": now,
    }
    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO prompt_template (
                  id, tenant_id, prompt_code, scope_level, scope_id, name,
                  description, status, active_version_id, owner_id, created_at, updated_at
                ) VALUES (
                  :id, :tenant_id, :prompt_code, :scope_level, :scope_id, :name,
                  :description, :status, :active_version_id, :owner_id, :created_at, :updated_at
                )
                """,
                item,
            )
    except Exception as exc:
        raise ApiError(HTTPStatus.CONFLICT, "Prompt template already exists for this scope") from exc
    write_audit_event(
        actor_id=actor_id,
        action="prompt_template.create",
        resource_type="prompt_template",
        resource_id=item["id"],
        scope_level=item["scope_level"],
        scope_id=item["scope_id"],
    )
    return item


def list_prompt_templates(query: dict[str, list[str]], actor_id: str) -> list[dict[str, Any]]:
    scope_level = _first(query, "scope_level")
    scope_id = _first(query, "scope_id")
    prompt_code = _first(query, "prompt_code")
    check_permission(
        actor_id=actor_id,
        action="read",
        resource_type="prompt_template",
        scope_level=scope_level,
        scope_id=scope_id,
    )
    clauses = ["1 = 1"]
    params: list[Any] = []
    if scope_level:
        clauses.append("scope_level = ?")
        params.append(scope_level)
    if scope_id:
        clauses.append("scope_id = ?")
        params.append(scope_id)
    if prompt_code:
        clauses.append("prompt_code = ?")
        params.append(prompt_code)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM prompt_template WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT 100",
            params,
        ).fetchall()
    write_audit_event(
        actor_id=actor_id,
        action="prompt_template.list",
        resource_type="prompt_template",
        scope_level=scope_level,
        scope_id=scope_id,
        detail={"count": len(rows)},
    )
    return rows_to_dicts(rows)


def create_prompt_version(template_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    require_fields(payload, ["content", "created_by"])
    template = _get_template(template_id)
    actor_id = payload["created_by"]
    check_permission(
        actor_id=actor_id,
        action="create_version",
        resource_type="prompt_template",
        resource_id=template_id,
        scope_level=template["scope_level"],
        scope_id=template["scope_id"],
    )
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version_no), 0) + 1 AS next_version FROM prompt_version WHERE template_id = ?",
            (template_id,),
        ).fetchone()
        version_no = int(row["next_version"])
        item = {
            "id": new_id("pv"),
            "template_id": template_id,
            "version_no": version_no,
            "content": payload["content"],
            "variables_schema": json.dumps(payload.get("variables_schema", {}), ensure_ascii=False),
            "change_note": payload.get("change_note"),
            "env": payload.get("env", "test"),
            "status": "draft",
            "created_by": actor_id,
            "published_at": None,
            "created_at": now_iso(),
        }
        conn.execute(
            """
            INSERT INTO prompt_version (
              id, template_id, version_no, content, variables_schema, change_note,
              env, status, created_by, published_at, created_at
            ) VALUES (
              :id, :template_id, :version_no, :content, :variables_schema, :change_note,
              :env, :status, :created_by, :published_at, :created_at
            )
            """,
            item,
        )
    write_audit_event(
        actor_id=actor_id,
        action="prompt_version.create",
        resource_type="prompt_version",
        resource_id=item["id"],
        scope_level=template["scope_level"],
        scope_id=template["scope_id"],
    )
    platform_binding = payload.get("platform_binding")
    if isinstance(platform_binding, dict):
        bind_prompt_version_to_platform(
            item["id"],
            {
                **platform_binding,
                "actor_id": actor_id,
            },
        )
    return item


def publish_prompt_version(version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("published_by")
    if not actor_id:
        raise ApiError(HTTPStatus.BAD_REQUEST, "actor_id or published_by is required")
    version = _get_version(version_id)
    template = _get_template(version["template_id"])
    check_permission(
        actor_id=actor_id,
        action="publish_version",
        resource_type="prompt_template",
        resource_id=template["id"],
        scope_level=template["scope_level"],
        scope_id=template["scope_id"],
    )
    now = now_iso()
    with connect() as conn:
        conn.execute(
            "UPDATE prompt_version SET status = 'published', published_at = ? WHERE id = ?",
            (now, version_id),
        )
        conn.execute(
            """
            UPDATE prompt_template
            SET status = 'active', active_version_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (version_id, now, template["id"]),
        )
    updated = _get_version(version_id)
    write_audit_event(
        actor_id=actor_id,
        action="prompt_version.publish",
        resource_type="prompt_version",
        resource_id=version_id,
        scope_level=template["scope_level"],
        scope_id=template["scope_id"],
    )
    return updated


def get_active_prompt_version(
    *,
    prompt_code: str,
    scope_level: str,
    scope_id: str,
    actor_id: str,
) -> dict[str, Any] | None:
    check_permission(
        actor_id=actor_id,
        action="read_active_version",
        resource_type="prompt_template",
        scope_level=scope_level,
        scope_id=scope_id,
    )
    with connect() as conn:
        row = conn.execute(
            """
            SELECT pv.*, pt.prompt_code, pt.scope_level, pt.scope_id
            FROM prompt_template pt
            JOIN prompt_version pv ON pv.id = pt.active_version_id
            WHERE pt.prompt_code = ?
              AND pt.scope_level = ?
              AND pt.scope_id = ?
              AND pt.status = 'active'
            """,
            (prompt_code, scope_level, scope_id),
        ).fetchone()
    return row_to_dict(row)


def list_prompt_versions(template_id: str, actor_id: str) -> list[dict[str, Any]]:
    template = _get_template(template_id)
    check_permission(
        actor_id=actor_id,
        action="read_versions",
        resource_type="prompt_template",
        resource_id=template_id,
        scope_level=template["scope_level"],
        scope_id=template["scope_id"],
    )
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM prompt_version WHERE template_id = ? ORDER BY version_no DESC",
            (template_id,),
        ).fetchall()
    write_audit_event(
        actor_id=actor_id,
        action="prompt_version.list",
        resource_type="prompt_version",
        resource_id=template_id,
        scope_level=template["scope_level"],
        scope_id=template["scope_id"],
        detail={"count": len(rows)},
    )
    items = rows_to_dicts(rows)
    for item in items:
        item["platform_bindings"] = list_prompt_platform_bindings(item["id"])
    return items


def _get_template(template_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM prompt_template WHERE id = ?", (template_id,)).fetchone()
    item = row_to_dict(row)
    if not item:
        raise ApiError(HTTPStatus.NOT_FOUND, "Prompt template not found")
    return item


def _get_version(version_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM prompt_version WHERE id = ?", (version_id,)).fetchone()
    item = row_to_dict(row)
    if not item:
        raise ApiError(HTTPStatus.NOT_FOUND, "Prompt version not found")
    item["platform_bindings"] = list_prompt_platform_bindings(item["id"])
    return item


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]
