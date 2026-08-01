from __future__ import annotations

import json
from typing import Any

from .audit import write_audit_event
from .config import use_remote_generation
from .control_center_messages import create_control_center_message
from .db import connect, rows_to_dicts
from .kimi_client import generate_llm_text
from .langfuse_platform import create_prompt_run_trace
from .permissions import check_permission


def get_project_history(project_id: str, query: dict[str, list[str]], actor_id: str) -> dict[str, Any]:
    check_permission(
        actor_id=actor_id,
        action="read",
        resource_type="control_center",
        scope_level="project",
        scope_id=project_id,
    )
    q = _first(query, "q") or ""
    needle = q.strip().lower()
    with connect() as conn:
        sessions = rows_to_dicts(
            conn.execute(
                """
                SELECT * FROM conversation_session
                WHERE project_id = ? AND status != 'deleted'
                ORDER BY updated_at DESC
                LIMIT 200
                """,
                (project_id,),
            ).fetchall()
        )
        messages = rows_to_dicts(
            conn.execute(
                """
                SELECT m.* FROM conversation_message m
                JOIN conversation_session s ON s.id = m.session_id
                WHERE m.project_id = ? AND s.status != 'deleted'
                ORDER BY m.created_at DESC
                LIMIT 500
                """,
                (project_id,),
            ).fetchall()
        )
        reports = rows_to_dicts(
            conn.execute(
                """
                SELECT r.* FROM work_report r
                JOIN conversation_session s ON s.id = r.session_id
                WHERE r.project_id = ? AND r.status != 'deleted' AND s.status != 'deleted'
                ORDER BY r.created_at DESC
                LIMIT 200
                """,
                (project_id,),
            ).fetchall()
        )
        handoffs = rows_to_dicts(
            conn.execute(
                """
                SELECT h.* FROM handoff_package h
                JOIN conversation_session s ON s.id = h.session_id
                WHERE h.project_id = ? AND h.status != 'deleted' AND s.status != 'deleted'
                ORDER BY h.created_at DESC
                LIMIT 200
                """,
                (project_id,),
            ).fetchall()
        )
        sync_packages = rows_to_dicts(
            conn.execute(
                """
                SELECT sp.* FROM sync_package sp
                LEFT JOIN conversation_session s ON s.id = sp.source_session_id
                WHERE sp.project_id = ? AND sp.status != 'deleted' AND sp.package_type = 'project_master'
                  AND (sp.source_session_id IS NULL OR s.status != 'deleted')
                ORDER BY version_no DESC
                LIMIT 200
                """,
                (project_id,),
            ).fetchall()
        )
        cross_refs = rows_to_dicts(
            conn.execute(
                """
                SELECT * FROM cross_project_reference
                WHERE target_project_id = ? AND status != 'deleted'
                ORDER BY created_at DESC
                LIMIT 200
                """,
                (project_id,),
            ).fetchall()
        )

    session_titles = {item["id"]: item["title"] for item in sessions}
    records: list[dict[str, Any]] = []
    records.extend(
        _record(
            kind="对话框",
            name=item["title"],
            project_id=project_id,
            session_id=item["id"],
            record_id=item["id"],
            content=_session_content(item),
            created_at=item.get("created_at"),
            updated_at=item.get("updated_at"),
        )
        for item in sessions
    )
    records.extend(
        _record(
            kind="对话消息",
            name=f"{session_titles.get(item['session_id'], '历史对话框')} / {item['role']}",
            project_id=project_id,
            session_id=item["session_id"],
            record_id=item["id"],
            content=item.get("content") or "",
            created_at=item.get("created_at"),
        )
        for item in messages
    )
    records.extend(
        _record(
            kind="工作汇报",
            name="工作汇报文件.md",
            project_id=project_id,
            session_id=item["session_id"],
            record_id=item["id"],
            content=item.get("content") or "",
            created_at=item.get("created_at"),
        )
        for item in reports
    )
    records.extend(
        _record(
            kind="工作交接",
            name="工作交接文件.json",
            project_id=project_id,
            session_id=item["session_id"],
            record_id=item["id"],
            content=item.get("package_json") or "",
            created_at=item.get("created_at"),
        )
        for item in handoffs
    )
    records.extend(
        _record(
            kind="传承包",
            name=f"传承包_v{item['version_no']}.md",
            project_id=project_id,
            session_id=item.get("source_session_id"),
            record_id=item["id"],
            content=item.get("content") or "",
            created_at=item.get("created_at"),
        )
        for item in sync_packages
    )
    records.extend(
        _record(
            kind="跨项目引用",
            name=item["source_name"],
            project_id=project_id,
            session_id=item.get("source_session_id"),
            record_id=item["id"],
            content=_cross_reference_content(item),
            created_at=item.get("created_at"),
        )
        for item in cross_refs
    )

    if needle:
        records = [item for item in records if needle in item["search_text"]]
    records.sort(key=lambda item: item.get("created_at") or item.get("updated_at") or "", reverse=True)

    result = {
        "project_id": project_id,
        "query": q,
        "summary": {
            "session_count": len(sessions),
            "message_count": len(messages),
            "work_report_count": len(reports),
            "handoff_file_count": len(handoffs),
            "sync_package_count": len(sync_packages),
            "cross_project_reference_count": len(cross_refs),
            "matched_count": len(records),
        },
        "records": records[:200],
    }
    write_audit_event(
        actor_id=actor_id,
        action="control_center.history.read",
        resource_type="control_center",
        scope_level="project",
        scope_id=project_id,
        detail={"query": q, "matched_count": len(records)},
    )
    return result


def get_platform_history(query: dict[str, list[str]], actor_id: str) -> dict[str, Any]:
    check_permission(
        actor_id=actor_id,
        action="read",
        resource_type="platform_control_center",
        scope_level="platform",
        scope_id="global",
    )
    q = _first(query, "q") or ""
    needle = q.strip().lower()
    included_project_ids = _project_id_set(_first(query, "include_project_ids") or "")
    excluded_project_ids = _project_id_set(_first(query, "exclude_project_ids") or "")
    records = _collect_records(project_id=None)
    if included_project_ids:
        records = [item for item in records if item.get("project_id") in included_project_ids]
    if excluded_project_ids:
        records = [item for item in records if item.get("project_id") not in excluded_project_ids]
    all_records = list(records)
    if needle:
        records = [item for item in records if needle in item["search_text"]]
    records.sort(key=lambda item: item.get("created_at") or item.get("updated_at") or "", reverse=True)
    if included_project_ids:
        project_ids = sorted(included_project_ids - excluded_project_ids)
    else:
        project_ids = sorted({item["project_id"] for item in all_records if item.get("project_id")})
    result = {
        "scope": "platform",
        "project_id": None,
        "query": q,
        "summary": {
            "project_count": len(project_ids),
            "record_count": len(all_records),
            "matched_count": len(records),
        },
        "records": records[:300],
    }
    write_audit_event(
        actor_id=actor_id,
        action="platform_control_center.history.read",
        resource_type="platform_control_center",
        scope_level="platform",
        scope_id="global",
        detail={"query": q, "matched_count": len(records)},
    )
    return result


def answer_project_history(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("created_by") or "system"
    question = (payload.get("question") or payload.get("q") or "").strip()
    if not question:
        question = "请帮我查找当前项目历史。"
    create_control_center_message(
        scope_level="project",
        scope_id=project_id,
        role="user",
        content=question,
        actor_id=actor_id,
    )
    if _is_cross_project_query(question):
        history = {
            "project_id": project_id,
            "query": question,
            "summary": {"matched_count": 0, "blocked_cross_project": True},
            "records": [],
            "redirect_to": "platform_control_center",
        }
        answer = (
            "这是跨项目检索需求。项目控制中心只能检索当前项目内的对话框、工作汇报、工作交接文件和传承包；"
            "请前往账号级总控制中心进行跨项目检索。"
        )
        write_audit_event(
            actor_id=actor_id,
            action="control_center.cross_project.blocked",
            resource_type="control_center",
            scope_level="project",
            scope_id=project_id,
            detail={"question": question},
        )
        result_payload = {
            "answer": answer,
            "history": history,
            "llm": {"provider": "policy"},
            "redirect_to": "platform_control_center",
        }
        _save_control_center_answer("project", project_id, answer, actor_id, "policy / boundary", result_payload)
        return result_payload
    history = get_project_history(project_id, {"q": [question]}, actor_id)
    records = history.get("records", [])[:12]
    if not records:
        answer = (
            f"没有在当前项目中找到和「{question}」直接相关的历史。"
            "可以换一个关键词，或打开历史文件中心查看全部记录。"
        )
        result_payload = {"answer": answer, "history": history, "llm": {"provider": "builtin"}}
        _save_control_center_answer("project", project_id, answer, actor_id, "builtin / readonly", result_payload)
        return result_payload

    if not use_remote_generation():
        answer = _builtin_answer(question, records)
        result_payload = {"answer": answer, "history": history, "llm": {"provider": "builtin"}}
        _save_control_center_answer("project", project_id, answer, actor_id, "builtin / readonly", result_payload)
        return result_payload

    system_prompt = (
        "你是项目控制中心的只读检索助手。"
        "你可以根据检索结果回答用户问题，并指出应该打开哪些对话框或记录。"
        "你不能执行业务任务，不能生成工作汇报、工作交接文件或传承包，不能触发自动传承。"
        "回答要简洁，必须保留 session_id 和 record_id，方便前端生成链接。"
    )
    user_prompt = json.dumps(
        {
            "question": question,
            "records": [
                {
                    "kind": item.get("kind"),
                    "name": item.get("name"),
                    "session_id": item.get("session_id"),
                    "record_id": item.get("record_id"),
                    "content_excerpt": (item.get("content") or "")[:1200],
                }
                for item in records
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    result = generate_llm_text(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_completion_tokens=int(payload.get("max_completion_tokens") or 1200),
        temperature=float(payload.get("temperature") or 0.2),
        safety_identifier=actor_id,
    )
    trace = create_prompt_run_trace(
        {
            "operation": "control_center.answer",
            "project_id": project_id,
            "input": {"question": question, "record_count": len(records), "llm": _model_call_meta(result)},
            "output_text": result["content"],
            "total_tokens": _estimate_tokens(user_prompt + result["content"]),
            "created_by": actor_id,
        }
    )
    write_audit_event(
        actor_id=actor_id,
        action="control_center.answer",
        resource_type="control_center",
        scope_level="project",
        scope_id=project_id,
        trace_id=trace["id"],
        detail={"question": question, "matched_count": len(records)},
    )
    result_payload = {
        "answer": result["content"],
        "history": history,
        "trace": trace,
        "llm": _model_call_meta(result),
    }
    _save_control_center_answer(
        "project",
        project_id,
        result["content"],
        actor_id,
        f"{result.get('provider') or 'remote'} / {result.get('model') or 'readonly'}",
        result_payload,
    )
    return result_payload


def answer_platform_history(payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("created_by") or "system"
    question = (payload.get("question") or payload.get("q") or "").strip()
    if not question:
        question = "请帮我查找平台历史。"
    create_control_center_message(
        scope_level="platform",
        scope_id="global",
        role="user",
        content=question,
        actor_id=actor_id,
    )
    exclude_project_ids = payload.get("exclude_project_ids") or []
    include_project_ids = payload.get("include_project_ids") or []
    if isinstance(include_project_ids, str):
        include_value = include_project_ids
    else:
        include_value = ",".join(str(item) for item in include_project_ids)
    if isinstance(exclude_project_ids, str):
        exclude_value = exclude_project_ids
    else:
        exclude_value = ",".join(str(item) for item in exclude_project_ids)
    history = get_platform_history(
        {
            "q": [question],
            "include_project_ids": [include_value],
            "exclude_project_ids": [exclude_value],
        },
        actor_id,
    )
    records = history.get("records", [])[:16]
    if not records:
        answer = f"没有在平台历史中找到和「{question}」直接相关的记录。可以换一个关键词或先缩小到某个项目。"
        result_payload = {"answer": answer, "history": history, "llm": {"provider": "builtin"}}
        _save_control_center_answer("platform", "global", answer, actor_id, "builtin / readonly", result_payload)
        return result_payload
    if not use_remote_generation():
        answer = _builtin_answer(question, records)
        result_payload = {"answer": answer, "history": history, "llm": {"provider": "builtin"}}
        _save_control_center_answer("platform", "global", answer, actor_id, "builtin / readonly", result_payload)
        return result_payload
    system_prompt = (
        "你是平台总控制中心的只读检索助手。"
        "你可以跨项目解释检索结果，并指出应该打开哪个项目、哪个对话框或记录。"
        "你不能执行业务任务，不能生成工作汇报、工作交接文件或传承包，不能触发自动传承。"
        "回答要简洁，必须保留 project_id、session_id 和 record_id，方便前端生成链接。"
    )
    user_prompt = json.dumps(
        {
            "question": question,
            "records": [
                {
                    "project_id": item.get("project_id"),
                    "kind": item.get("kind"),
                    "name": item.get("name"),
                    "session_id": item.get("session_id"),
                    "record_id": item.get("record_id"),
                    "content_excerpt": (item.get("content") or "")[:1000],
                }
                for item in records
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    result = generate_llm_text(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_completion_tokens=int(payload.get("max_completion_tokens") or 1400),
        temperature=float(payload.get("temperature") or 0.2),
        safety_identifier=actor_id,
    )
    trace = create_prompt_run_trace(
        {
            "operation": "platform_control_center.answer",
            "input": {"question": question, "record_count": len(records), "llm": _model_call_meta(result)},
            "output_text": result["content"],
            "total_tokens": _estimate_tokens(user_prompt + result["content"]),
            "created_by": actor_id,
        }
    )
    write_audit_event(
        actor_id=actor_id,
        action="platform_control_center.answer",
        resource_type="platform_control_center",
        scope_level="platform",
        scope_id="global",
        trace_id=trace["id"],
        detail={"question": question, "matched_count": len(records)},
    )
    result_payload = {"answer": result["content"], "history": history, "trace": trace, "llm": _model_call_meta(result)}
    _save_control_center_answer(
        "platform",
        "global",
        result["content"],
        actor_id,
        f"{result.get('provider') or 'remote'} / {result.get('model') or 'readonly'}",
        result_payload,
    )
    return result_payload


def _collect_records(project_id: str | None) -> list[dict[str, Any]]:
    project_filter = "WHERE project_id = ?" if project_id else ""
    params: tuple[Any, ...] = (project_id,) if project_id else ()
    with connect() as conn:
        sessions = rows_to_dicts(
            conn.execute(
                f"""
                SELECT * FROM conversation_session
                {project_filter}
                {"WHERE status != 'deleted'" if not project_id else "AND status != 'deleted'"}
                ORDER BY updated_at DESC
                LIMIT 500
                """,
                params,
            ).fetchall()
        )
        messages = rows_to_dicts(
            conn.execute(
                f"""
                SELECT m.* FROM conversation_message m
                JOIN conversation_session s ON s.id = m.session_id
                {"WHERE m.project_id = ? AND s.status != 'deleted'" if project_id else "WHERE s.status != 'deleted'"}
                ORDER BY m.created_at DESC
                LIMIT 1000
                """,
                params,
            ).fetchall()
        )
        reports = rows_to_dicts(
            conn.execute(
                f"""
                SELECT r.* FROM work_report r
                JOIN conversation_session s ON s.id = r.session_id
                WHERE r.status != 'deleted' AND s.status != 'deleted' {"AND r.project_id = ?" if project_id else ""}
                ORDER BY r.created_at DESC
                LIMIT 500
                """,
                params,
            ).fetchall()
        )
        handoffs = rows_to_dicts(
            conn.execute(
                f"""
                SELECT h.* FROM handoff_package h
                JOIN conversation_session s ON s.id = h.session_id
                WHERE h.status != 'deleted' AND s.status != 'deleted' {"AND h.project_id = ?" if project_id else ""}
                ORDER BY h.created_at DESC
                LIMIT 500
                """,
                params,
            ).fetchall()
        )
        sync_packages = rows_to_dicts(
            conn.execute(
                f"""
                SELECT sp.* FROM sync_package sp
                LEFT JOIN conversation_session s ON s.id = sp.source_session_id
                WHERE sp.status != 'deleted'
                  AND sp.package_type = 'project_master'
                  AND (sp.source_session_id IS NULL OR s.status != 'deleted')
                  {"AND sp.project_id = ?" if project_id else ""}
                ORDER BY sp.version_no DESC
                LIMIT 500
                """,
                params,
            ).fetchall()
        )
    session_titles = {item["id"]: item["title"] for item in sessions}
    records: list[dict[str, Any]] = []
    records.extend(
        _record(
            kind="对话框",
            name=item["title"],
            project_id=item["project_id"],
            session_id=item["id"],
            record_id=item["id"],
            content=_session_content(item),
            created_at=item.get("created_at"),
            updated_at=item.get("updated_at"),
        )
        for item in sessions
    )
    records.extend(
        _record(
            kind="对话消息",
            name=f"{session_titles.get(item['session_id'], '历史对话框')} / {item['role']}",
            project_id=item["project_id"],
            session_id=item["session_id"],
            record_id=item["id"],
            content=item.get("content") or "",
            created_at=item.get("created_at"),
        )
        for item in messages
    )
    records.extend(
        _record(
            kind="工作汇报",
            name="工作汇报文件.md",
            project_id=item["project_id"],
            session_id=item["session_id"],
            record_id=item["id"],
            content=item.get("content") or "",
            created_at=item.get("created_at"),
        )
        for item in reports
    )
    records.extend(
        _record(
            kind="工作交接",
            name="工作交接文件.json",
            project_id=item["project_id"],
            session_id=item["session_id"],
            record_id=item["id"],
            content=item.get("package_json") or "",
            created_at=item.get("created_at"),
        )
        for item in handoffs
    )
    records.extend(
        _record(
            kind="传承包",
            name=f"传承包_v{item['version_no']}.md",
            project_id=item["project_id"],
            session_id=item.get("source_session_id"),
            record_id=item["id"],
            content=item.get("content") or "",
            created_at=item.get("created_at"),
        )
        for item in sync_packages
    )
    return records


def _record(
    *,
    kind: str,
    name: str,
    project_id: str,
    session_id: str | None,
    record_id: str,
    content: str,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    text = "\n".join([kind, name, project_id, session_id or "", record_id, content]).lower()
    return {
        "kind": kind,
        "name": name,
        "project_id": project_id,
        "session_id": session_id,
        "record_id": record_id,
        "content": content,
        "created_at": created_at,
        "updated_at": updated_at,
        "search_text": text,
    }


def _session_content(item: dict[str, Any]) -> str:
    parts = [
        f"title: {item.get('title')}",
        f"status: {item.get('status')}",
        f"capacity: {item.get('used_units')}/{item.get('capacity_limit')} ({item.get('capacity_ratio')})",
        f"auto_handoff_done: {item.get('auto_handoff_done')}",
        f"next_session_id: {item.get('next_session_id')}",
        item.get("summary") or "",
        item.get("open_todos") or "",
        item.get("decisions") or "",
        item.get("risks") or "",
    ]
    return "\n".join(str(part) for part in parts if part is not None)


def _cross_reference_content(item: dict[str, Any]) -> str:
    parts = [
        f"source_project_id: {item.get('source_project_id')}",
        f"source_record_type: {item.get('source_record_type')}",
        f"source_record_id: {item.get('source_record_id')}",
        f"source_session_id: {item.get('source_session_id')}",
        f"source_name: {item.get('source_name')}",
        item.get("source_excerpt") or "",
        item.get("note") or "",
    ]
    return "\n".join(str(part) for part in parts if part)


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]


def _project_id_set(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def _save_control_center_answer(
    scope_level: str,
    scope_id: str,
    answer: str,
    actor_id: str,
    meta: str,
    result: dict[str, Any],
) -> None:
    create_control_center_message(
        scope_level=scope_level,
        scope_id=scope_id,
        role="assistant",
        content=answer,
        actor_id=actor_id,
        meta=meta,
        result=result,
    )


def _builtin_answer(question: str, records: list[dict[str, Any]]) -> str:
    lines = [f"我找到了和「{question}」相关的记录，建议优先打开这些对话框："]
    for index, item in enumerate(records[:5], start=1):
        project_part = f"project_id: {item.get('project_id')}, " if item.get("project_id") else ""
        lines.append(
            f"{index}. {item.get('name')} / {item.get('kind')} "
            f"({project_part}session_id: {item.get('session_id') or '无'}, record_id: {item.get('record_id')})"
        )
    lines.append("控制中心只负责检索和解释结果，不会执行业务或触发传承。")
    return "\n".join(lines)


def _is_cross_project_query(question: str) -> bool:
    normalized = question.strip().lower()
    if not normalized:
        return False
    cross_markers = [
        "跨项目",
        "其他项目",
        "其它项目",
        "别的项目",
        "不同项目",
        "所有项目",
        "全部项目",
        "全项目",
        "各项目",
        "总控制中心",
        "平台控制中心",
        "平台总控制中心",
        "同一甲方",
        "同一个甲方",
        "同一客户",
        "同一个客户",
        "cross project",
        "cross-project",
        "other project",
        "other projects",
        "all projects",
        "same client",
        "same customer",
    ]
    if any(marker in normalized for marker in cross_markers):
        return True
    return ("项目1" in normalized or "项目一" in normalized) and (
        "项目2" in normalized or "项目二" in normalized
    ) or ("project1" in normalized and "project2" in normalized)


def _model_call_meta(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": result.get("provider") or "remote",
        "model": result.get("model"),
        "response_id": result.get("response_id"),
        "usage": result.get("usage") or {},
    }


def _estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))
