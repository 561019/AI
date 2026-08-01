from __future__ import annotations

from typing import Any

from .audit import write_audit_event
from .db import connect, rows_to_dicts
from .permissions import check_permission


def get_prompt_governance(project_id: str, actor_id: str) -> dict[str, Any]:
    check_permission(
        actor_id=actor_id,
        action="read",
        resource_type="prompt_governance",
        scope_level="project",
        scope_id=project_id,
    )
    with connect() as conn:
        templates = rows_to_dicts(
            conn.execute(
                """
                SELECT * FROM prompt_template
                WHERE scope_level = 'project' AND scope_id = ?
                ORDER BY prompt_code, updated_at DESC
                """,
                (project_id,),
            ).fetchall()
        )
        versions = rows_to_dicts(
            conn.execute(
                """
                SELECT pv.*, pt.prompt_code, pt.name AS template_name,
                       pt.active_version_id
                FROM prompt_version pv
                JOIN prompt_template pt ON pt.id = pv.template_id
                WHERE pt.scope_level = 'project' AND pt.scope_id = ?
                ORDER BY pt.prompt_code, pv.version_no DESC
                """,
                (project_id,),
            ).fetchall()
        )
        bindings = rows_to_dicts(
            conn.execute(
                """
                SELECT ppb.*, pv.template_id, pt.prompt_code
                FROM prompt_platform_binding ppb
                JOIN prompt_version pv ON pv.id = ppb.prompt_version_id
                JOIN prompt_template pt ON pt.id = pv.template_id
                WHERE pt.scope_level = 'project' AND pt.scope_id = ?
                ORDER BY ppb.updated_at DESC
                """,
                (project_id,),
            ).fetchall()
        )
        traces = rows_to_dicts(
            conn.execute(
                """
                SELECT prt.*, pv.version_no, pt.prompt_code
                FROM prompt_run_trace prt
                LEFT JOIN prompt_version pv ON pv.id = prt.prompt_version_id
                LEFT JOIN prompt_template pt ON pt.id = pv.template_id
                WHERE prt.project_id = ?
                ORDER BY prt.created_at DESC
                LIMIT 100
                """,
                (project_id,),
            ).fetchall()
        )
    summary = {
        "template_count": len(templates),
        "version_count": len(versions),
        "binding_count": len(bindings),
        "trace_count": len(traces),
        "active_template_count": len([item for item in templates if item.get("status") == "active"]),
    }
    write_audit_event(
        actor_id=actor_id,
        action="prompt_governance.read",
        resource_type="prompt_governance",
        scope_level="project",
        scope_id=project_id,
        detail=summary,
    )
    return {
        "project_id": project_id,
        "summary": summary,
        "templates": templates,
        "versions": versions,
        "bindings": bindings,
        "traces": traces,
    }
