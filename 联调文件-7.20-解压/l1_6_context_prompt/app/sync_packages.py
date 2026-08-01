from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

from .artifacts import create_artifact_file
from .audit import write_audit_event
from .config import use_remote_generation
from .db import connect, row_to_dict, rows_to_dicts
from .kimi_client import generate_llm_text, json_for_prompt
from .langfuse_platform import create_prompt_run_trace, fetch_langfuse_prompt
from .permissions import check_permission
from .prompts import get_active_prompt_version
from .utils import ApiError, new_id, now_iso


SYNC_PACKAGE_PROMPT_CODE = "sync_package_compress"


def upgrade_sync_package(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("created_by") or "system"
    check_permission(
        actor_id=actor_id,
        action="upgrade",
        resource_type="sync_package",
        scope_level="project",
        scope_id=project_id,
    )
    work_report = _resolve_work_report(project_id, payload)
    previous = get_latest_sync_package(project_id, actor_id, raise_if_missing=False)
    prompt_ref = _resolve_prompt(project_id, actor_id)
    content, model_call = _generate_sync_package_content(project_id, previous, work_report, prompt_ref, actor_id)
    version_no = _next_version_no(project_id, "project_master")
    structured = _build_structured_package(
        project_id=project_id,
        version_no=version_no,
        previous=previous,
        work_report=work_report,
        prompt_ref=prompt_ref,
        content=content,
    )

    artifact = create_artifact_file(
        {
            "project_id": project_id,
            "session_id": work_report.get("session_id"),
            "artifact_type": "sync_package",
            "title": f"Project {project_id} 同步包/传承包 v{version_no}",
            "summary": "由指挥中心根据最新工作汇报升级形成的长期上下文文件。",
            "storage_ref": f"sqlite://sync_package/{project_id}/v{version_no}",
            "content": content,
            "created_by": actor_id,
        }
    )
    trace = create_prompt_run_trace(
        {
            "operation": "sync_package.upgrade",
            "prompt_version_id": prompt_ref.get("local_prompt_version_id"),
            "project_id": project_id,
            "session_id": work_report.get("session_id"),
            "input": {
                "previous_sync_package_id": previous.get("id") if previous else None,
                "work_report_id": work_report.get("id"),
                "prompt_ref": prompt_ref,
                "llm": model_call,
            },
            "output_text": content,
            "total_tokens": _estimate_tokens(content),
            "created_by": actor_id,
        }
    )
    item = {
        "id": new_id("sync"),
        "project_id": project_id,
        "version_no": version_no,
        "package_type": "project_master",
        "source_work_report_id": work_report.get("id"),
        "source_session_id": work_report.get("session_id"),
        "prompt_version_id": prompt_ref.get("local_prompt_version_id"),
        "prompt_source": prompt_ref["source"],
        "prompt_name": prompt_ref["name"],
        "prompt_label": prompt_ref.get("label"),
        "prompt_platform_version": _as_text(prompt_ref.get("version")),
        "langfuse_prompt_id": prompt_ref.get("langfuse_prompt_id"),
        "trace_id": trace["id"],
        "artifact_file_id": artifact["id"],
        "content": content,
        "structured_json": json.dumps(structured, ensure_ascii=False, indent=2),
        "session_index": json.dumps(structured["session_index"], ensure_ascii=False),
        "file_index": json.dumps(structured["file_index"], ensure_ascii=False),
        "topic_index": json.dumps(structured["topic_index"], ensure_ascii=False),
        "pending_tasks": json.dumps(structured["pending_tasks"], ensure_ascii=False),
        "next_actions": json.dumps(structured["next_actions"], ensure_ascii=False),
        "status": "active",
        "created_by": actor_id,
        "created_at": now_iso(),
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO sync_package (
              id, project_id, version_no, package_type, source_work_report_id, source_session_id,
              prompt_version_id, prompt_source, prompt_name, prompt_label,
              prompt_platform_version, langfuse_prompt_id, trace_id, artifact_file_id,
              content, structured_json, session_index, file_index, topic_index,
              pending_tasks, next_actions, status, created_by, created_at
            ) VALUES (
              :id, :project_id, :version_no, :package_type, :source_work_report_id, :source_session_id,
              :prompt_version_id, :prompt_source, :prompt_name, :prompt_label,
              :prompt_platform_version, :langfuse_prompt_id, :trace_id, :artifact_file_id,
              :content, :structured_json, :session_index, :file_index, :topic_index,
              :pending_tasks, :next_actions, :status, :created_by, :created_at
            )
            """,
            item,
        )
    write_audit_event(
        actor_id=actor_id,
        action="sync_package.upgrade",
        resource_type="sync_package",
        resource_id=item["id"],
        scope_level="project",
        scope_id=project_id,
        detail={
            "version_no": version_no,
            "source_work_report_id": item["source_work_report_id"],
            "prompt_source": prompt_ref["source"],
            "prompt_name": prompt_ref["name"],
        },
    )
    item["artifact_file"] = artifact
    item["langfuse_trace"] = trace
    item["prompt_ref"] = prompt_ref
    item["llm"] = model_call
    item["previous_sync_package"] = previous
    item["work_report"] = work_report
    return item


def get_latest_sync_package(
    project_id: str,
    actor_id: str,
    *,
    raise_if_missing: bool = True,
) -> dict[str, Any] | None:
    check_permission(
        actor_id=actor_id,
        action="read",
        resource_type="sync_package",
        scope_level="project",
        scope_id=project_id,
    )
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM sync_package
            WHERE project_id = ? AND package_type = 'project_master' AND status != 'deleted'
            ORDER BY version_no DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
    item = row_to_dict(row)
    if not item and raise_if_missing:
        raise ApiError(HTTPStatus.NOT_FOUND, "Sync package not found")
    return item


def list_sync_packages(project_id: str, query: dict[str, list[str]], actor_id: str) -> list[dict[str, Any]]:
    check_permission(
        actor_id=actor_id,
        action="read",
        resource_type="sync_package",
        scope_level="project",
        scope_id=project_id,
    )
    limit = int(_first(query, "limit") or 50)
    limit = max(1, min(limit, 200))
    package_type = _first(query, "package_type")
    clauses = ["project_id = ?", "status != 'deleted'"]
    params: list[Any] = [project_id]
    if package_type:
        clauses.append("package_type = ?")
        params.append(package_type)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM sync_package
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC, version_no DESC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()
    write_audit_event(
        actor_id=actor_id,
        action="sync_package.list",
        resource_type="sync_package",
        scope_level="project",
        scope_id=project_id,
        detail={"count": len(rows)},
    )
    return rows_to_dicts(rows)


def delete_sync_package(project_id: str, sync_package_id: str, actor_id: str) -> dict[str, Any]:
    check_permission(
        actor_id=actor_id,
        action="delete",
        resource_type="sync_package",
        scope_level="project",
        scope_id=project_id,
    )
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM sync_package
            WHERE id = ? AND project_id = ?
            """,
            (sync_package_id, project_id),
        ).fetchone()
        item = row_to_dict(row)
        if not item:
            raise ApiError(HTTPStatus.NOT_FOUND, "Sync package not found")
        conn.execute(
            """
            UPDATE sync_package
            SET status = 'deleted'
            WHERE id = ? AND project_id = ?
            """,
            (sync_package_id, project_id),
        )
    write_audit_event(
        actor_id=actor_id,
        action="sync_package.delete",
        resource_type="sync_package",
        resource_id=sync_package_id,
        scope_level="project",
        scope_id=project_id,
    )
    deleted = dict(item)
    deleted["status"] = "deleted"
    return deleted


def _resolve_work_report(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    work_report_id = payload.get("work_report_id")
    if work_report_id:
        with connect() as conn:
            row = conn.execute("SELECT * FROM work_report WHERE id = ?", (work_report_id,)).fetchone()
    else:
        session_id = payload.get("session_id")
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        with connect() as conn:
            row = conn.execute(
                f"SELECT * FROM work_report WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT 1",
                params,
            ).fetchone()
    item = row_to_dict(row)
    if not item:
        raise ApiError(HTTPStatus.BAD_REQUEST, "work_report_id or an existing project work report is required")
    if item["project_id"] != project_id:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Work report does not belong to this project")
    return item


def _next_version_no(project_id: str, package_type: str) -> int:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(version_no), 0) + 1 AS next_version
            FROM sync_package
            WHERE project_id = ? AND package_type = ?
            """,
            (project_id, package_type),
        ).fetchone()
    return int(row["next_version"])


def _build_structured_package(
    *,
    project_id: str,
    version_no: int,
    previous: dict[str, Any] | None,
    work_report: dict[str, Any],
    prompt_ref: dict[str, Any],
    content: str,
) -> dict[str, Any]:
    session_id = work_report.get("session_id")
    report_id = work_report.get("id")
    return {
        "schema_version": "sync_package.project_master.v1",
        "package_type": "project_master",
        "project_id": project_id,
        "version_no": version_no,
        "source": {
            "work_report_id": report_id,
            "session_id": session_id,
            "previous_sync_package_id": previous.get("id") if previous else None,
        },
        "prompt": {
            "source": prompt_ref.get("source"),
            "name": prompt_ref.get("name"),
            "version": prompt_ref.get("version"),
            "label": prompt_ref.get("label"),
            "local_prompt_version_id": prompt_ref.get("local_prompt_version_id"),
            "langfuse_prompt_id": prompt_ref.get("langfuse_prompt_id"),
        },
        "session_index": [
            {
                "session_id": session_id,
                "source_work_report_id": report_id,
                "summary": _first_lines(work_report.get("content") or "", 6),
            }
        ],
        "file_index": [
            {
                "artifact_file_id": work_report.get("artifact_file_id"),
                "kind": "work_report",
                "source_session_id": session_id,
            }
        ],
        "topic_index": _extract_topic_index(content),
        "pending_tasks": _extract_bullets(content, ["待办", "未完成", "下一步"]),
        "next_actions": _extract_bullets(content, ["下一轮", "下一步", "建议"]),
        "compressed_summary": _first_lines(content, 12),
        "created_at": now_iso(),
    }


def _first_lines(text: str, count: int) -> str:
    return "\n".join(str(text or "").splitlines()[:count])


def _extract_topic_index(text: str) -> list[dict[str, str]]:
    topics: list[dict[str, str]] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            topics.append({"topic": stripped.lstrip("#").strip(), "source": "heading"})
    return topics[:20]


def _extract_bullets(text: str, headings: list[str]) -> list[str]:
    results: list[str] = []
    capture = False
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            capture = any(word in stripped for word in headings)
            continue
        if capture and stripped.startswith(("-", "*", "1.", "2.", "3.", "4.", "5.")):
            results.append(stripped.lstrip("-* ").strip())
    return results[:20]


def _resolve_prompt(project_id: str, actor_id: str) -> dict[str, Any]:
    try:
        langfuse_prompt = fetch_langfuse_prompt(SYNC_PACKAGE_PROMPT_CODE, "production")["prompt"]
        return {
            "source": "langfuse",
            "name": langfuse_prompt.get("name") or SYNC_PACKAGE_PROMPT_CODE,
            "version": langfuse_prompt.get("version"),
            "label": "production",
            "type": langfuse_prompt.get("type"),
            "content": langfuse_prompt.get("prompt") or "",
            "langfuse_prompt_id": langfuse_prompt.get("id"),
            "local_prompt_version_id": None,
        }
    except Exception as exc:
        local_prompt = get_active_prompt_version(
            prompt_code=SYNC_PACKAGE_PROMPT_CODE,
            scope_level="project",
            scope_id=project_id,
            actor_id=actor_id,
        )
        if local_prompt:
            return {
                "source": "local",
                "name": SYNC_PACKAGE_PROMPT_CODE,
                "version": local_prompt.get("version_no"),
                "label": "active",
                "type": "text",
                "content": local_prompt.get("content") or "",
                "langfuse_prompt_id": None,
                "local_prompt_version_id": local_prompt.get("id"),
                "fallback_reason": str(exc),
            }
        return {
            "source": "builtin",
            "name": SYNC_PACKAGE_PROMPT_CODE,
            "version": None,
            "label": None,
            "type": "text",
            "content": "",
            "langfuse_prompt_id": None,
            "local_prompt_version_id": None,
            "fallback_reason": str(exc),
        }


def _render_sync_package(
    project_id: str,
    previous: dict[str, Any] | None,
    work_report: dict[str, Any],
    prompt_ref: dict[str, Any],
) -> str:
    version_no = (previous["version_no"] + 1) if previous else 1
    previous_content = previous.get("content") if previous else "首次创建，暂无旧同步包/传承包。"
    lines = [
        f"# Project {project_id} 同步包/传承包 v{version_no}",
        "",
        "## 文件定位",
        "同步包/传承包是 Project 知识库中的长期历史上下文，由指挥中心根据工作汇报升级维护。",
        "它不是工作交接文件；新对话框启动时应先读最新同步包/传承包，再读上一轮工作交接文件。",
        "",
        "## Prompt 来源",
        _prompt_line(prompt_ref),
        "",
        "## 上一版同步包/传承包",
        previous_content,
        "",
        "## 本轮工作汇报",
        work_report.get("content") or "",
        "",
        "## 本版升级摘要",
        "- 已把本轮工作汇报中的项目进展、决策、待办和风险合并进长期上下文。",
        "- 继续保持同步包/传承包、工作汇报文件、工作交接文件三者边界清晰。",
        "- 下一轮新对话框应先读取本文件，再读取上一轮工作交接文件。",
        "",
        "## Langfuse Production Prompt",
        prompt_ref.get("content") or "未读取到平台提示词，使用内置 MVP 合并结构。",
    ]
    return "\n".join(lines)


def _generate_sync_package_content(
    project_id: str,
    previous: dict[str, Any] | None,
    work_report: dict[str, Any],
    prompt_ref: dict[str, Any],
    actor_id: str,
) -> tuple[str, dict[str, Any]]:
    if not use_remote_generation():
        return _render_sync_package(project_id, previous, work_report, prompt_ref), {"provider": "builtin"}
    result = generate_llm_text(
        system_prompt=_kimi_system_prompt(prompt_ref),
        user_prompt=json_for_prompt(
            {
                "project_id": project_id,
                "previous_sync_package": previous,
                "work_report": work_report,
            }
        ),
        max_completion_tokens=4096,
        temperature=0.2,
        prompt_cache_key=f"sync_package:{project_id}",
        safety_identifier=actor_id,
    )
    return result["content"], _model_call_meta(result)


def _kimi_system_prompt(prompt_ref: dict[str, Any]) -> str:
    prompt = (prompt_ref.get("content") or "").strip()
    if prompt:
        return prompt
    return (
        "你是 Project 指挥中心的同步包/传承包压缩助手。"
        "请根据旧版同步包/传承包和最新工作汇报生成新版中文 Markdown 传承包。"
        "必须保持同步包/传承包、工作汇报文件、工作交接文件三者边界清晰。"
    )


def _model_call_meta(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": result.get("provider") or "remote",
        "model": result.get("model"),
        "response_id": result.get("response_id"),
        "usage": result.get("usage") or {},
    }


def _prompt_line(prompt_ref: dict[str, Any]) -> str:
    version = prompt_ref.get("version")
    label = prompt_ref.get("label")
    if version is None:
        return f"{prompt_ref['source']} / {prompt_ref['name']}"
    return f"{prompt_ref['source']} / {prompt_ref['name']} v{version} ({label})"


def _estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]
