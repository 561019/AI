from __future__ import annotations

from http import HTTPStatus
from typing import Any

from .audit import write_audit_event
from .cross_project_references import list_cross_project_references
from .db import connect, rows_to_dicts
from .handoff_runs import start_handoff_run
from .kimi_client import generate_llm_text
from .langfuse_platform import create_prompt_run_trace
from .sessions import get_session, lock_session, update_session_capacity
from .utils import ApiError, new_id, now_iso


CHAT_SYSTEM_PROMPT = (
    "你是当前项目普通对话框里的工作助手。"
    "你可以正常回答用户问题、协助分析和推进工作。"
    "不要假装已经生成工作汇报、工作交接文件或传承包；这些由系统在自动传承流程中生成。"
    "如果用户要求查看历史文件或控制中心内容，提醒用户去控制中心或历史文件中心。"
)

HANDOFF_RATIO = 0.85
LOCK_RATIO = 1.0


def chat_with_session(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("created_by") or "system"
    user_text = (payload.get("message") or payload.get("text") or "").strip()
    if not user_text:
        raise ApiError(HTTPStatus.BAD_REQUEST, "message is required")

    session = get_session(session_id, actor_id)
    if session.get("locked") or session.get("capacity_ratio", 0) >= LOCK_RATIO:
        raise ApiError(HTTPStatus.LOCKED, "该对话框已达到 100% 容量并锁定，只能翻阅历史记录。")

    recent_messages = list_session_messages(session_id, actor_id, limit=12)
    user_tokens = _estimate_tokens(user_text)
    ratio_after_user = _projected_ratio(session, user_tokens)
    if ratio_after_user >= LOCK_RATIO:
        user_message = _store_message(
            session=session,
            role="user",
            content=user_text,
            actor_id=actor_id,
        )
        updated = update_session_capacity(
            session_id,
            {"delta_units": user_tokens, "actor_id": actor_id},
        )
        if not updated.get("locked"):
            updated = lock_session(session_id, actor_id)
        return {
            "auto_handoff": False,
            "locked": True,
            "user_message": user_message,
            "session": updated,
            "reply": None,
            "message": "本次输入后容量达到 100%，对话框已锁定。AI 回复不会生成，请新建对话框继续。",
        }

    user_message = _store_message(
        session=session,
        role="user",
        content=user_text,
        actor_id=actor_id,
    )

    estimated_reply_units = int(payload.get("estimated_reply_units") or 300)
    estimated_ratio = _projected_ratio(session, user_tokens + estimated_reply_units)
    if _should_auto_handoff(session, ratio_after_user, estimated_ratio):
        run = start_handoff_run(
            session_id,
            {
                "actor_id": actor_id,
                "user_text": user_text,
                "user_message_id": user_message["id"],
                "user_tokens": user_tokens,
            },
        )
        write_audit_event(
            actor_id=actor_id,
            action="session.auto_handoff_start",
            resource_type="conversation_session",
            resource_id=session_id,
            scope_level="project",
            scope_id=session["project_id"],
            detail={"handoff_run_id": run["id"], "estimated_ratio": estimated_ratio},
        )
        return {
            "auto_handoff": True,
            "handoff_run": run,
            "handoff_run_id": run["id"],
            "old_session": run["old_session"],
            "new_session": run["new_session"],
        }

    reference_context = _references_for_user_text(session, actor_id, user_text)
    result = generate_llm_text(
        system_prompt=_build_system_prompt(session),
        user_prompt=_build_user_prompt(session, recent_messages, user_text, reference_context),
        max_completion_tokens=int(payload.get("max_completion_tokens") or 1200),
        temperature=float(payload.get("temperature") or 0.4),
        safety_identifier=actor_id,
    )
    assistant_text = result["content"]
    assistant_tokens = _estimate_tokens(assistant_text)
    projected_ratio = _projected_ratio(session, user_tokens + assistant_tokens)

    trace = create_prompt_run_trace(
        {
            "operation": "session.chat",
            "project_id": session["project_id"],
            "session_id": session_id,
            "input": {
                "session": session,
                "recent_message_count": len(recent_messages),
                "user_text": user_text,
                "cross_project_reference_count": len(reference_context),
                "llm": _model_call_meta(result),
            },
            "output_text": assistant_text,
            "total_tokens": user_tokens + assistant_tokens,
            "created_by": actor_id,
        }
    )

    assistant_message = _store_message(
        session=session,
        role="assistant",
        content=assistant_text,
        actor_id=actor_id,
        model_provider=result.get("provider"),
        model_name=result.get("model"),
        trace_id=trace["id"],
    )
    updated_session = update_session_capacity(
        session_id,
        {"delta_units": user_tokens + assistant_tokens, "actor_id": actor_id},
    )
    write_audit_event(
        actor_id=actor_id,
        action="session.chat",
        resource_type="conversation_session",
        resource_id=session_id,
        scope_level="project",
        scope_id=session["project_id"],
        detail={"trace_id": trace["id"], "auto_handoff": False},
    )
    return {
        "reply": assistant_text,
        "assistant_message": assistant_message,
        "session": updated_session,
        "trace": trace,
        "llm": _model_call_meta(result),
        "auto_handoff": False,
        "used_cross_project_references": reference_context,
    }


def list_session_messages(
    session_id: str, actor_id: str, limit: int = 100
) -> list[dict[str, Any]]:
    session = get_session(session_id, actor_id)
    limit = max(1, min(int(limit), 200))
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM conversation_message
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    messages = rows_to_dicts(rows)
    messages.reverse()
    write_audit_event(
        actor_id=actor_id,
        action="session.messages.list",
        resource_type="conversation_session",
        resource_id=session_id,
        scope_level="project",
        scope_id=session["project_id"],
        detail={"count": len(messages)},
    )
    return messages


def _should_auto_handoff(
    session: dict[str, Any], ratio_after_user: float, projected_ratio: float
) -> bool:
    if session.get("auto_handoff_done"):
        return False
    if float(session.get("capacity_ratio") or 0) >= HANDOFF_RATIO:
        return False
    return ratio_after_user < LOCK_RATIO and projected_ratio >= HANDOFF_RATIO


def _projected_ratio(session: dict[str, Any], delta: int) -> float:
    projected = int(session["used_units"]) + delta
    limit = int(session["capacity_limit"])
    return round(min(projected / limit, 1.0), 4)


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


def _build_system_prompt(session: dict[str, Any]) -> str:
    return "\n".join(
        [
            CHAT_SYSTEM_PROMPT,
            f"project_id: {session['project_id']}",
            f"session_id: {session['id']}",
            f"session_title: {session['title']}",
        ]
    )


def _build_user_prompt(
    session: dict[str, Any],
    recent_messages: list[dict[str, Any]],
    user_text: str,
    reference_context: list[dict[str, Any]] | None = None,
) -> str:
    lines = [
        "当前会话摘要：",
        session.get("summary") or "暂无摘要。",
        "",
        "最近对话：",
    ]
    for message in recent_messages:
        lines.append(f"{message['role']}: {message['content']}")
    if reference_context:
        lines.extend(
            [
                "",
                "当前项目已导入/已引用的跨项目内容：",
                "这些内容已经进入当前项目边界，可以作为本轮回答参考；不要再跨项目检索。",
            ]
        )
        for index, item in enumerate(reference_context[:5], start=1):
            lines.extend(
                [
                    f"{index}. 来源项目：{item.get('source_project_id')}",
                    f"   来源类型：{item.get('source_record_type')}",
                    f"   record_id：{item.get('source_record_id')}",
                    f"   标题：{item.get('source_name')}",
                    f"   摘要：{item.get('source_excerpt')}",
                ]
            )
    lines.extend(["", "用户最新输入：", user_text])
    return "\n".join(lines)


def _references_for_user_text(
    session: dict[str, Any], actor_id: str, user_text: str
) -> list[dict[str, Any]]:
    # Always fetch cross-project references — the AI can use them as needed
    references = list_cross_project_references(session["project_id"], actor_id)
    if not references:
        return []
    needle = _reference_query_needle(user_text)
    if not needle:
        return references[:5]
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in references:
        text = "\n".join(
            [
                item.get("source_project_id") or "",
                item.get("source_record_type") or "",
                item.get("source_record_id") or "",
                item.get("source_name") or "",
                item.get("source_excerpt") or "",
                item.get("note") or "",
            ]
        ).lower()
        score = sum(1 for token in needle if token and token in text)
        if score:
            scored.append((score, item))
    if not scored:
        return references[:5]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:5]]


def _asks_for_imported_references(user_text: str) -> bool:
    text = user_text.lower()
    markers = [
        "已导入",
        "已经导入",
        "导入该项目",
        "已引用",
        "已经引用",
        "引用内容",
        "引用的内容",
        "跨项目引用",
        "参考引用",
        "参考已导入",
        "参考已经导入",
        "参考已引用",
    ]
    return any(marker in text for marker in markers)


def _reference_query_needle(user_text: str) -> list[str]:
    stop_words = [
        "参考",
        "已经",
        "已导入",
        "导入",
        "该项目",
        "当前项目",
        "内容",
        "文件",
        "帮我",
        "完成",
        "某项任务",
        "已引用",
        "引用",
        "跨项目",
    ]
    text = user_text.lower()
    for word in stop_words:
        text = text.replace(word, " ")
    return [part.strip() for part in text.replace("，", " ").replace("。", " ").split() if len(part.strip()) >= 2]


def _model_call_meta(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": result.get("provider") or "remote",
        "model": result.get("model"),
        "response_id": result.get("response_id"),
        "usage": result.get("usage") or {},
    }


def _estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))
