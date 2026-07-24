from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4


def make_internal_envelope(trace_id: str, actor: dict[str, Any], task_id: str, capability: str, target_layer: str, target_module: str, payload: dict[str, Any], *, source_layer: str = "business_engine", source_module: str = "workflow-execution", context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "protocol_version": "1.0", "message_id": str(uuid4()), "request_id": str(uuid4()),
        "trace_id": trace_id, "parent_request_id": None,
        "source": {"layer": source_layer, "module": source_module},
        "target": {"layer": target_layer, "module": target_module, "capability": capability},
        "actor": {**actor, "authenticated": bool(actor.get("authenticated", True))},
        "context": {"project_id": "platform-runtime", "conversation_id": task_id, "locale": "zh-CN", **(context or {})},
        "request_type": "execute", "action": capability,
        "payload": {**payload, "platform_task_id": task_id},
        "expected_response": {"mode": "sync"}, "idempotency_key": f"internal-{capability}-{task_id}",
        "deadline_at": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
    }
