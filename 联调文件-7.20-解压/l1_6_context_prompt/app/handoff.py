from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

from .artifacts import create_artifact_file
from .audit import write_audit_event
from .config import use_remote_generation
from .db import connect, rows_to_dicts
from .kimi_client import generate_llm_text, json_for_prompt
from .langfuse_platform import create_prompt_run_trace, fetch_langfuse_prompt
from .prompts import get_active_prompt_version
from .sessions import get_session
from .utils import ApiError, new_id, now_iso


REPORT_PROMPT_CODE = "work_report"
HANDOFF_PROMPT_CODE = "handoff_file"


def generate_work_report(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("created_by") or "system"
    session = get_session(session_id, actor_id)
    prompt_ref = _resolve_prompt(REPORT_PROMPT_CODE, session, actor_id)
    content, model_call = _generate_work_report_content(session, prompt_ref, actor_id)
    artifact = create_artifact_file(
        {
            "project_id": session["project_id"],
            "session_id": session_id,
            "artifact_type": "work_report",
            "title": f"{session['title']} - 工作汇报",
            "summary": f"会话 {session['title']} 的阶段性工作汇报。",
            "storage_ref": f"sqlite://work_report/{session_id}",
            "content": content,
            "created_by": actor_id,
        }
    )
    item = {
        "id": new_id("report"),
        "project_id": session["project_id"],
        "session_id": session_id,
        "prompt_version_id": prompt_ref.get("local_prompt_version_id"),
        "artifact_file_id": artifact["id"],
        "content": content,
        "status": "generated",
        "created_by": actor_id,
        "created_at": now_iso(),
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO work_report (
              id, project_id, session_id, prompt_version_id, artifact_file_id,
              content, status, created_by, created_at
            ) VALUES (
              :id, :project_id, :session_id, :prompt_version_id, :artifact_file_id,
              :content, :status, :created_by, :created_at
            )
            """,
            item,
        )
    trace = create_prompt_run_trace(
        {
            "operation": "work_report.generate",
            "prompt_version_id": prompt_ref.get("local_prompt_version_id"),
            "project_id": session["project_id"],
            "session_id": session_id,
            "input": {"session": session, "prompt_ref": prompt_ref, "llm": model_call},
            "output_text": content,
            "total_tokens": _estimate_tokens(content),
            "created_by": actor_id,
        }
    )
    write_audit_event(
        actor_id=actor_id,
        action="work_report.generate",
        resource_type="work_report",
        resource_id=item["id"],
        scope_level="project",
        scope_id=item["project_id"],
        detail={"prompt_source": prompt_ref["source"], "prompt_name": prompt_ref["name"]},
    )
    item["artifact_file"] = artifact
    item["langfuse_trace"] = trace
    item["prompt_ref"] = prompt_ref
    item["llm"] = model_call
    return item


def generate_handoff_file(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("created_by") or "system"
    session = get_session(session_id, actor_id)
    prompt_ref = _resolve_prompt(HANDOFF_PROMPT_CODE, session, actor_id)
    handoff_json, handoff_file, model_call = _generate_handoff_content(session, prompt_ref, actor_id)
    artifact = create_artifact_file(
        {
            "project_id": session["project_id"],
            "session_id": session_id,
            "artifact_type": "handoff_file",
            "title": f"{session['title']} - 工作交接文件",
            "summary": "给下一个对话框直接读取的工作交接文件。",
            "storage_ref": f"sqlite://handoff_file/{session_id}",
            "content": handoff_json,
            "created_by": actor_id,
        }
    )
    item = {
        "id": new_id("handoff"),
        "project_id": session["project_id"],
        "session_id": session_id,
        "prompt_version_id": prompt_ref.get("local_prompt_version_id"),
        "artifact_file_id": artifact["id"],
        "package_json": handoff_json,
        "status": "generated",
        "created_by": actor_id,
        "created_at": now_iso(),
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO handoff_package (
              id, project_id, session_id, prompt_version_id, artifact_file_id,
              package_json, status, created_by, created_at
            ) VALUES (
              :id, :project_id, :session_id, :prompt_version_id, :artifact_file_id,
              :package_json, :status, :created_by, :created_at
            )
            """,
            item,
        )
        conn.execute(
            """
            UPDATE conversation_session
            SET status = 'closed', updated_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (actor_id, now_iso(), session_id),
        )
    trace = create_prompt_run_trace(
        {
            "operation": "handoff_file.generate",
            "prompt_version_id": prompt_ref.get("local_prompt_version_id"),
            "project_id": session["project_id"],
            "session_id": session_id,
            "input": {"session": session, "prompt_ref": prompt_ref, "llm": model_call},
            "output_text": handoff_json,
            "total_tokens": _estimate_tokens(handoff_json),
            "created_by": actor_id,
        }
    )
    write_audit_event(
        actor_id=actor_id,
        action="handoff_file.generate",
        resource_type="handoff_file",
        resource_id=item["id"],
        scope_level="project",
        scope_id=item["project_id"],
        detail={"prompt_source": prompt_ref["source"], "prompt_name": prompt_ref["name"]},
    )
    item["handoff_file"] = handoff_file
    item["artifact_file"] = artifact
    item["langfuse_trace"] = trace
    item["prompt_ref"] = prompt_ref
    item["llm"] = model_call
    return item


def generate_handoff_package(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return generate_handoff_file(session_id, payload)


def close_session(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    report = generate_work_report(session_id, payload)
    handoff = generate_handoff_file(session_id, payload)
    return {"work_report": report, "handoff_file": handoff, "handoff_package": handoff}


def list_work_reports(query: dict[str, list[str]], actor_id: str) -> list[dict[str, Any]]:
    return _list_generated("work_report", query, actor_id)


def list_handoff_files(query: dict[str, list[str]], actor_id: str) -> list[dict[str, Any]]:
    return _list_generated("handoff_package", query, actor_id)


def list_handoff_packages(query: dict[str, list[str]], actor_id: str) -> list[dict[str, Any]]:
    return list_handoff_files(query, actor_id)


def delete_work_report(report_id: str, actor_id: str) -> dict[str, Any]:
    return _mark_generated_deleted("work_report", report_id, actor_id)


def delete_handoff_file(handoff_id: str, actor_id: str) -> dict[str, Any]:
    return _mark_generated_deleted("handoff_package", handoff_id, actor_id)


def _resolve_prompt(prompt_code: str, session: dict[str, Any], actor_id: str) -> dict[str, Any]:
    try:
        langfuse_prompt = fetch_langfuse_prompt(prompt_code, "production")["prompt"]
        return {
            "source": "langfuse",
            "name": langfuse_prompt.get("name") or prompt_code,
            "version": langfuse_prompt.get("version"),
            "label": "production",
            "type": langfuse_prompt.get("type"),
            "content": langfuse_prompt.get("prompt") or "",
            "langfuse_prompt_id": langfuse_prompt.get("id"),
            "local_prompt_version_id": None,
        }
    except Exception as exc:
        local_prompt = get_active_prompt_version(
            prompt_code=prompt_code,
            scope_level="project",
            scope_id=session["project_id"],
            actor_id=actor_id,
        )
        if local_prompt:
            return {
                "source": "local",
                "name": prompt_code,
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
            "name": prompt_code,
            "version": None,
            "label": None,
            "type": "text",
            "content": "",
            "langfuse_prompt_id": None,
            "local_prompt_version_id": None,
            "fallback_reason": str(exc),
        }


def _generate_work_report_content(
    session: dict[str, Any],
    prompt_ref: dict[str, Any],
    actor_id: str,
) -> tuple[str, dict[str, Any]]:
    messages = _session_messages_for_generation(session["id"], actor_id)
    if not use_remote_generation():
        return _render_work_report(session, prompt_ref), {"provider": "builtin"}
    result = generate_llm_text(
        system_prompt=_kimi_system_prompt(prompt_ref, "请生成中文 Markdown 工作汇报文件。"),
        user_prompt=json_for_prompt({"session": session, "messages": messages}),
        max_completion_tokens=2048,
        temperature=0.2,
        prompt_cache_key=f"work_report:{session['project_id']}",
        safety_identifier=actor_id,
    )
    return result["content"], _model_call_meta(result)


def _generate_handoff_content(
    session: dict[str, Any],
    prompt_ref: dict[str, Any],
    actor_id: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    messages = _session_messages_for_generation(session["id"], actor_id)
    if not use_remote_generation():
        handoff_file = _build_handoff_file(session, prompt_ref)
        return json.dumps(handoff_file, ensure_ascii=False, indent=2), handoff_file, {"provider": "builtin"}
    result = generate_llm_text(
        system_prompt=_kimi_system_prompt(
            prompt_ref,
            (
                "请生成严格 JSON，不要输出 Markdown。JSON 必须描述工作交接文件，"
                "包含 project_id、source_session_id、已完成事项、下一步、必须读取文件、未完成事项、风险。"
            ),
        ),
        user_prompt=json_for_prompt({"session": session, "messages": messages}),
        max_completion_tokens=2048,
        temperature=0.1,
        prompt_cache_key=f"handoff_file:{session['project_id']}",
        safety_identifier=actor_id,
    )
    handoff_json = result["content"].strip()
    try:
        handoff_file = json.loads(handoff_json)
    except json.JSONDecodeError:
        handoff_file = {"content": handoff_json}
        handoff_json = json.dumps(handoff_file, ensure_ascii=False, indent=2)
    return handoff_json, handoff_file, _model_call_meta(result)


def _kimi_system_prompt(prompt_ref: dict[str, Any], fallback_instruction: str) -> str:
    prompt = (prompt_ref.get("content") or "").strip()
    if prompt:
        return prompt
    return fallback_instruction


def _model_call_meta(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": result.get("provider") or "remote",
        "model": result.get("model"),
        "response_id": result.get("response_id"),
        "usage": result.get("usage") or {},
    }


def _session_messages_for_generation(session_id: str, actor_id: str) -> list[dict[str, Any]]:
    try:
        from .chat import list_session_messages

        return list_session_messages(session_id, actor_id, limit=80)
    except Exception:
        return []


def _render_work_report(session: dict[str, Any], prompt_ref: dict[str, Any]) -> str:
    prompt_line = _prompt_line(prompt_ref)
    lines = [
        f"# {session['title']} 工作汇报",
        "",
        prompt_line,
        f"Project：{session['project_id']}",
        f"容量：{session['used_units']}/{session['capacity_limit']} ({session['capacity_ratio']:.0%})",
        "",
        "## Langfuse Production Prompt",
        prompt_ref.get("content") or "未读取到平台提示词，使用内置 MVP 输出结构。",
        "",
        "## 当前进展",
        session.get("summary") or "暂无摘要。",
        "",
        "## 已确认决策",
        _bullet_lines(session.get("decisions") or ["暂无已确认决策。"]),
        "",
        "## 未完成事项",
        _bullet_lines(session.get("open_todos") or ["暂无未完成事项。"]),
        "",
        "## 风险与注意事项",
        _bullet_lines(session.get("risks") or ["暂无风险记录。"]),
        "",
        "## 需要写入同步包/传承包的事项",
        _bullet_lines((session.get("decisions") or []) + (session.get("open_todos") or [])),
    ]
    return "\n".join(lines)


def _build_handoff_file(session: dict[str, Any], prompt_ref: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "handoff_file.phase1.mvp.v1",
        "project_id": session["project_id"],
        "source_session_id": session["id"],
        "source_session_title": session["title"],
        "prompt": {
            "source": prompt_ref["source"],
            "name": prompt_ref["name"],
            "version": prompt_ref.get("version"),
            "label": prompt_ref.get("label"),
            "langfuse_prompt_id": prompt_ref.get("langfuse_prompt_id"),
            "local_prompt_version_id": prompt_ref.get("local_prompt_version_id"),
        },
        "capacity": {
            "used_units": session["used_units"],
            "capacity_limit": session["capacity_limit"],
            "capacity_ratio": session["capacity_ratio"],
        },
        "must_read_first": session.get("summary") or "",
        "confirmed_decisions": session.get("decisions") or [],
        "open_todos": session.get("open_todos") or [],
        "risks": session.get("risks") or [],
        "next_conversation_instruction": (
            "新对话框应先读取 Project 知识库中的最新同步包/传承包，"
            "再读取本工作交接文件，随后向用户确认下一步处理事项；"
            "如果用户给出新指令，以用户新指令为准。"
        ),
        "langfuse_production_prompt": prompt_ref.get("content") or "",
        "created_at": now_iso(),
    }


def _prompt_line(prompt_ref: dict[str, Any]) -> str:
    version = prompt_ref.get("version")
    label = prompt_ref.get("label")
    source = prompt_ref.get("source")
    if version is not None:
        return f"提示词来源：{source} / {prompt_ref['name']} v{version} ({label})"
    return f"提示词来源：{source} / {prompt_ref['name']}"


def _bullet_lines(items: list[Any]) -> str:
    return "\n".join([f"- {item}" for item in items])


def _estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))


def _list_generated(table: str, query: dict[str, list[str]], actor_id: str) -> list[dict[str, Any]]:
    project_id = _first(query, "project_id")
    session_id = _first(query, "session_id")
    clauses = ["status != 'deleted'"]
    params: list[Any] = []
    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT 100",
            params,
        ).fetchall()
    write_audit_event(
        actor_id=actor_id,
        action=f"{table}.list",
        resource_type=table,
        scope_level="project",
        scope_id=project_id,
        detail={"count": len(rows)},
    )
    return rows_to_dicts(rows)


def _mark_generated_deleted(table: str, item_id: str, actor_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
        item = rows_to_dicts([row])[0] if row else None
        if not item:
            raise ApiError(HTTPStatus.NOT_FOUND, "Generated file not found")
        conn.execute(f"UPDATE {table} SET status = 'deleted' WHERE id = ?", (item_id,))
    write_audit_event(
        actor_id=actor_id,
        action=f"{table}.delete",
        resource_type=table,
        resource_id=item_id,
        scope_level="project",
        scope_id=item.get("project_id"),
    )
    deleted = dict(item)
    deleted["status"] = "deleted"
    return deleted


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]
