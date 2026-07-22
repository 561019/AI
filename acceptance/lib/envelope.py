from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4


def make_envelope(
    *,
    actor: dict[str, Any],
    source_layer: str,
    source_module: str,
    target_layer: str,
    target_module: str,
    capability: str,
    action: str,
    request_type: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    return {
        "protocol_version": "1.0",
        "message_id": str(uuid4()),
        "request_id": str(uuid4()),
        "trace_id": trace_id or str(uuid4()),
        "parent_request_id": None,
        "source": {"layer": source_layer, "module": source_module},
        "target": {
            "layer": target_layer,
            "module": target_module,
            "capability": capability,
        },
        "actor": {**actor, "authenticated": True},
        "context": {
            "project_id": "acceptance-project",
            "conversation_id": "acceptance-conversation",
            "locale": "zh-CN",
        },
        "request_type": request_type,
        "action": action,
        "payload": payload,
        "expected_response": {"mode": "async"},
        "idempotency_key": idempotency_key or f"acceptance-{uuid4()}",
        "deadline_at": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
    }
