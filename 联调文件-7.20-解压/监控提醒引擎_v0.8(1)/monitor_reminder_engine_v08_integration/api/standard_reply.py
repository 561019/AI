from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _base(envelope: dict[str, Any]) -> dict[str, Any]:
    context = envelope.get("context", {})
    return {
        "protocol_version": "1.0",
        "message_id": f"msg_reply_{uuid4().hex}",
        "parent_message_id": envelope.get("message_id", ""),
        "trace_id": envelope.get("trace_id", ""),
        "request_id": envelope.get("request_id", ""),
        "task_id": context.get("task_id", ""),
        "timestamp": _now(),
    }


def success_reply(
    envelope: dict[str, Any],
    *,
    message: str,
    data: dict[str, Any] | None = None,
    status: str = "completed",
) -> dict[str, Any]:
    return {
        **_base(envelope),
        "reply_type": "success",
        "status": status,
        "message": message,
        "data": data or {},
    }


def accepted_reply(
    envelope: dict[str, Any],
    *,
    message: str,
    data: dict[str, Any] | None = None,
    status: str = "processing",
) -> dict[str, Any]:
    return {
        **_base(envelope),
        "reply_type": "accepted",
        "status": status,
        "message": message,
        "data": data or {},
    }


def failed_reply(
    envelope: dict[str, Any],
    *,
    code: str,
    message: str,
    retryable: bool = False,
    data: dict[str, Any] | None = None,
    status: str = "rejected",
) -> dict[str, Any]:
    return {
        **_base(envelope),
        "reply_type": "failed",
        "status": status,
        "message": message,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
        "data": data or {},
    }
