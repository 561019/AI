from __future__ import annotations

from http import HTTPStatus
from typing import Any

from .audit import write_audit_event
from .db import connect, rows_to_dicts
from .sessions import HANDOFF_RATIO, WARNING_RATIO, get_session, update_session_capacity
from .utils import ApiError, new_id, now_iso, require_fields


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    # Same rough class of fallback used by many local context-engineering MVPs.
    return max(1, round(len(text) / 4))


def estimate_context_payload(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload.get("text", "")
    token_count = int(payload.get("token_count") or estimate_tokens(text))
    context_window = int(payload.get("context_window") or payload.get("capacity_limit") or 0)
    ratio = round(token_count / context_window, 4) if context_window > 0 else None
    return {
        "estimated_tokens": token_count,
        "context_window": context_window or None,
        "capacity_ratio": ratio,
        "thresholds": {
            "warning_80": WARNING_RATIO,
            "force_handoff_85": HANDOFF_RATIO,
        },
        "status": _status_for_ratio(ratio),
    }


def add_context_usage(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("updated_by") or "system"
    text = payload.get("text", "")
    token_count = int(payload.get("token_count") or estimate_tokens(text))
    return update_session_capacity(session_id, {"delta_units": token_count, "actor_id": actor_id})


def compact_session_context(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor_id = payload.get("actor_id") or payload.get("created_by") or "system"
    session = get_session(session_id, actor_id)
    require_fields(payload, ["summary"])
    tokens_before = int(payload.get("tokens_before") or session["used_units"])
    tokens_after = int(payload.get("tokens_after") or estimate_tokens(payload["summary"]))
    if tokens_after > tokens_before:
        raise ApiError(HTTPStatus.BAD_REQUEST, "tokens_after cannot be greater than tokens_before")
    item = {
        "id": new_id("compact"),
        "session_id": session_id,
        "strategy": payload.get("strategy", "summarization"),
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "messages_before": int(payload.get("messages_before", 0)),
        "messages_after": int(payload.get("messages_after", 0)),
        "summary": payload["summary"],
        "created_by": actor_id,
        "created_at": now_iso(),
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO context_compaction (
              id, session_id, strategy, tokens_before, tokens_after,
              messages_before, messages_after, summary, created_by, created_at
            ) VALUES (
              :id, :session_id, :strategy, :tokens_before, :tokens_after,
              :messages_before, :messages_after, :summary, :created_by, :created_at
            )
            """,
            item,
        )
    write_audit_event(
        actor_id=actor_id,
        action="context.compaction.create",
        resource_type="context_compaction",
        resource_id=item["id"],
        scope_level="project",
        scope_id=session["project_id"],
        detail={"tokens_before": tokens_before, "tokens_after": tokens_after},
    )
    return item


def list_context_compactions(session_id: str, actor_id: str) -> list[dict[str, Any]]:
    get_session(session_id, actor_id)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM context_compaction WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
    return rows_to_dicts(rows)


def _status_for_ratio(ratio: float | None) -> str:
    if ratio is None:
        return "unknown"
    if ratio >= HANDOFF_RATIO:
        return "force_handoff"
    if ratio >= WARNING_RATIO:
        return "warning"
    return "ok"
