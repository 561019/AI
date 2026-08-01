from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

from .audit import write_audit_event
from .db import connect, row_to_dict
from .handoff import generate_handoff_file, generate_work_report
from .kimi_client import generate_llm_text
from .langfuse_platform import create_prompt_run_trace
from .sessions import create_session, get_session, mark_auto_handoff_done, update_session_capacity
from .sync_packages import upgrade_sync_package
from .utils import ApiError, new_id, now_iso


def start_handoff_run(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("created_by") or "system"
    session = get_session(session_id, actor_id)
    if session.get("auto_handoff_done"):
        raise ApiError(HTTPStatus.CONFLICT, "该对话框已经自动传承过，不能重复触发。")
    if session.get("locked") or session.get("capacity_ratio", 0) >= 1.0:
        raise ApiError(HTTPStatus.LOCKED, "该对话框已锁定，不能自动传承。")

    user_text = (payload.get("user_text") or payload.get("message") or "").strip()
    if not user_text:
        raise ApiError(HTTPStatus.BAD_REQUEST, "user_text is required")
    user_tokens = int(payload.get("user_tokens") or _estimate_tokens(user_text))

    user_message_id = payload.get("user_message_id")
    if not user_message_id:
        user_message_id = _store_message(
            session=session,
            role="user",
            content=user_text,
            actor_id=actor_id,
        )["id"]

    old_session = update_session_capacity(
        session_id,
        {"delta_units": user_tokens, "actor_id": actor_id},
    )
    new_session = create_session(
        {
            "project_id": session["project_id"],
            "title": _next_dialog_title(session["title"]),
            "capacity_limit": int(session["capacity_limit"]),
            "used_units": 0,
            "summary": (
                f"从「{session['title']}」自动传承而来。"
                "请先读取最新传承包和工作交接文件，再继续与用户确认下一步。"
            ),
            "open_todos": session.get("open_todos") or [],
            "decisions": session.get("decisions") or [],
            "risks": session.get("risks") or [],
            "created_by": actor_id,
        }
    )
    now = now_iso()
    item = {
        "id": new_id("handoffrun"),
        "project_id": session["project_id"],
        "old_session_id": session_id,
        "new_session_id": new_session["id"],
        "status": "started",
        "user_message_id": user_message_id,
        "assistant_message_id": None,
        "trace_id": payload.get("trace_id"),
        "work_report_id": None,
        "handoff_file_id": None,
        "sync_package_id": None,
        "user_text": user_text,
        "assistant_text": payload.get("assistant_text"),
        "llm_meta": json.dumps(payload.get("llm_meta") or {}, ensure_ascii=False),
        "created_by": actor_id,
        "created_at": now,
        "updated_at": now,
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO handoff_run (
              id, project_id, old_session_id, new_session_id, status,
              user_message_id, assistant_message_id, trace_id, work_report_id,
              handoff_file_id, sync_package_id, user_text, assistant_text, llm_meta,
              created_by, created_at, updated_at
            ) VALUES (
              :id, :project_id, :old_session_id, :new_session_id, :status,
              :user_message_id, :assistant_message_id, :trace_id, :work_report_id,
              :handoff_file_id, :sync_package_id, :user_text, :assistant_text, :llm_meta,
              :created_by, :created_at, :updated_at
            )
            """,
            item,
        )
    return _decorate(item, actor_id, old_session=old_session, new_session=new_session)


def write_handoff_reply(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("created_by") or "system"
    run = _get_run(run_id)
    if run.get("assistant_message_id"):
        return _decorate(run, actor_id)
    assistant_text = run.get("assistant_text") or ""
    llm_meta = _json_loads(run.get("llm_meta"))
    trace_id = run.get("trace_id")
    if not assistant_text:
        old_session = get_session(run["old_session_id"], actor_id)
        recent_messages = _session_messages(run["old_session_id"])
        result = generate_llm_text(
            system_prompt=_build_system_prompt(old_session),
            user_prompt=_build_user_prompt(old_session, recent_messages, run["user_text"]),
            max_completion_tokens=int(payload.get("max_completion_tokens") or 1200),
            temperature=float(payload.get("temperature") or 0.4),
            safety_identifier=actor_id,
        )
        assistant_text = result["content"]
        llm_meta = _model_call_meta(result)
        trace = create_prompt_run_trace(
            {
                "operation": "session.auto_handoff.reply",
                "project_id": run["project_id"],
                "session_id": run["old_session_id"],
                "input": {
                    "old_session": old_session,
                    "new_session_id": run["new_session_id"],
                    "recent_message_count": len(recent_messages),
                    "user_text": run["user_text"],
                    "llm": llm_meta,
                },
                "output_text": assistant_text,
                "total_tokens": _estimate_tokens(run["user_text"] + assistant_text),
                "created_by": actor_id,
            }
        )
        trace_id = trace["id"]
    message = {
        "id": new_id("msg"),
        "session_id": run["new_session_id"],
        "project_id": run["project_id"],
        "role": "assistant",
        "content": assistant_text,
        "token_estimate": _estimate_tokens(assistant_text),
        "model_provider": llm_meta.get("provider"),
        "model_name": llm_meta.get("model"),
        "trace_id": trace_id,
        "created_by": actor_id,
        "created_at": now_iso(),
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO conversation_message (
              id, session_id, project_id, role, content, token_estimate,
              model_provider, model_name, trace_id, created_by, created_at
            ) VALUES (
              :id, :session_id, :project_id, :role, :content, :token_estimate,
              :model_provider, :model_name, :trace_id, :created_by, :created_at
            )
            """,
            message,
        )
        conn.execute(
            """
            UPDATE handoff_run
            SET assistant_message_id = ?, assistant_text = ?, trace_id = ?,
                llm_meta = ?, status = 'reply_written', updated_at = ?
            WHERE id = ?
            """,
            (
                message["id"],
                assistant_text,
                trace_id,
                json.dumps(llm_meta, ensure_ascii=False),
                now_iso(),
                run_id,
            ),
        )
    update_session_capacity(
        run["new_session_id"],
        {"delta_units": message["token_estimate"], "actor_id": actor_id},
    )
    return _decorate(_get_run(run_id), actor_id, assistant_message=message)


def generate_run_work_report(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("created_by") or "system"
    run = _get_run(run_id)
    if run.get("work_report_id"):
        return _decorate(run, actor_id)
    report = generate_work_report(run["old_session_id"], {"actor_id": actor_id})
    _update_run(run_id, "work_report_id", report["id"], "work_report_generated")
    return _decorate(_get_run(run_id), actor_id, work_report=report)


def generate_run_handoff_file(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("created_by") or "system"
    run = _get_run(run_id)
    if run.get("handoff_file_id"):
        return _decorate(run, actor_id)
    handoff = generate_handoff_file(run["old_session_id"], {"actor_id": actor_id})
    _update_run(run_id, "handoff_file_id", handoff["id"], "handoff_file_generated")
    return _decorate(_get_run(run_id), actor_id, handoff_file=handoff)


def upgrade_run_sync_package(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("created_by") or "system"
    run = _get_run(run_id)
    if run.get("sync_package_id"):
        return _decorate(run, actor_id)
    if not run.get("work_report_id"):
        raise ApiError(HTTPStatus.CONFLICT, "请先生成工作汇报文件。")
    sync = upgrade_sync_package(
        run["project_id"],
        {"work_report_id": run["work_report_id"], "actor_id": actor_id},
    )
    _update_run(run_id, "sync_package_id", sync["id"], "sync_package_upgraded")
    return _decorate(_get_run(run_id), actor_id, sync_package=sync)


def complete_handoff_run(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("created_by") or "system"
    run = _get_run(run_id)
    if not run.get("assistant_message_id"):
        raise ApiError(HTTPStatus.CONFLICT, "请先迁移本轮 AI 回复。")
    if not run.get("work_report_id") or not run.get("handoff_file_id") or not run.get("sync_package_id"):
        raise ApiError(HTTPStatus.CONFLICT, "请先生成工作汇报、工作交接文件和传承包。")
    old_session = mark_auto_handoff_done(
        run["old_session_id"],
        run["new_session_id"],
        actor_id,
    )
    with connect() as conn:
        conn.execute(
            "UPDATE handoff_run SET status = 'completed', updated_at = ? WHERE id = ?",
            (now_iso(), run_id),
        )
    write_audit_event(
        actor_id=actor_id,
        action="handoff_run.complete",
        resource_type="handoff_run",
        resource_id=run_id,
        scope_level="project",
        scope_id=run["project_id"],
    )
    return _decorate(_get_run(run_id), actor_id, old_session=old_session)


def get_handoff_run(run_id: str, actor_id: str) -> dict[str, Any]:
    return _decorate(_get_run(run_id), actor_id)


def _get_run(run_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM handoff_run WHERE id = ?", (run_id,)).fetchone()
    item = row_to_dict(row)
    if not item:
        raise ApiError(HTTPStatus.NOT_FOUND, "Handoff run not found")
    return item


def _decorate(
    item: dict[str, Any],
    actor_id: str,
    **overrides: Any,
) -> dict[str, Any]:
    run = dict(item)
    run["llm_meta"] = _json_loads(run.get("llm_meta"))
    result = dict(run)
    result["old_session"] = overrides.get("old_session") or get_session(run["old_session_id"], actor_id)
    result["new_session"] = overrides.get("new_session") or get_session(run["new_session_id"], actor_id)
    if overrides.get("assistant_message"):
        result["assistant_message"] = overrides["assistant_message"]
    result["work_report"] = overrides.get("work_report") or _fetch_by_id(
        "work_report", run.get("work_report_id")
    )
    result["handoff_file"] = overrides.get("handoff_file") or _fetch_by_id(
        "handoff_package", run.get("handoff_file_id")
    )
    result["sync_package"] = overrides.get("sync_package") or _fetch_by_id(
        "sync_package", run.get("sync_package_id")
    )
    result["reply"] = run.get("assistant_text")
    result["llm"] = run["llm_meta"]
    result.update({key: value for key, value in overrides.items() if key not in {"old_session", "new_session"}})
    return result


def _fetch_by_id(table: str, item_id: str | None) -> dict[str, Any] | None:
    if not item_id:
        return None
    allowed = {"work_report", "handoff_package", "sync_package"}
    if table not in allowed:
        return None
    with connect() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    return row_to_dict(row)


def _store_message(
    *,
    session: dict[str, Any],
    role: str,
    content: str,
    actor_id: str,
    model_provider: str | None = None,
    model_name: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    item = {
        "id": new_id("msg"),
        "session_id": session["id"],
        "project_id": session["project_id"],
        "role": role,
        "content": content,
        "token_estimate": _estimate_tokens(content),
        "model_provider": model_provider,
        "model_name": model_name,
        "trace_id": trace_id,
        "created_by": actor_id,
        "created_at": now_iso(),
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO conversation_message (
              id, session_id, project_id, role, content, token_estimate,
              model_provider, model_name, trace_id, created_by, created_at
            ) VALUES (
              :id, :session_id, :project_id, :role, :content, :token_estimate,
              :model_provider, :model_name, :trace_id, :created_by, :created_at
            )
            """,
            item,
        )
    return item


def _session_messages(session_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM conversation_message
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT 12
            """,
            (session_id,),
        ).fetchall()
    messages = [row_to_dict(row) for row in rows if row is not None]
    messages.reverse()
    return messages


def _build_system_prompt(session: dict[str, Any]) -> str:
    return "\n".join(
        [
            "你是当前项目普通对话框里的工作助手。请正常回答用户问题，输出将写入新的续接对话框。",
            "不要假装已经生成工作汇报、工作交接文件或传承包；这些由系统后续步骤生成。",
            f"project_id: {session['project_id']}",
            f"source_session_id: {session['id']}",
            f"source_session_title: {session['title']}",
        ]
    )


def _build_user_prompt(
    session: dict[str, Any], recent_messages: list[dict[str, Any]], user_text: str
) -> str:
    lines = [
        "当前会话摘要：",
        session.get("summary") or "暂无摘要。",
        "",
        "最近对话：",
    ]
    for message in recent_messages:
        lines.append(f"{message['role']}: {message['content']}")
    lines.extend(["", "用户最新输入：", user_text])
    return "\n".join(lines)


def _model_call_meta(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": result.get("provider") or "remote",
        "model": result.get("model"),
        "response_id": result.get("response_id"),
        "usage": result.get("usage") or {},
    }


def _update_run(run_id: str, column: str, value: str, status: str) -> None:
    allowed = {"work_report_id", "handoff_file_id", "sync_package_id"}
    if column not in allowed:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Invalid handoff run column")
    with connect() as conn:
        conn.execute(
            f"UPDATE handoff_run SET {column} = ?, status = ?, updated_at = ? WHERE id = ?",
            (value, status, now_iso(), run_id),
        )


def _json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _next_dialog_title(current_title: str) -> str:
    return f"{current_title} (续)"


def _estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))
