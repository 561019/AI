from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
from core.errors import BusinessError


def _parse_time(value):
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class MessageContractValidator:
    def __init__(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config" / "source_route_matrix.json"
        self.config = json.loads(path.read_text(encoding="utf-8"))

    def validate(self, message) -> None:
        required = {
            "message_id": message.message_id,
            "trace_id": message.trace_id,
            "request_id": message.request_id,
            "idempotency_key": message.idempotency_key,
            "actor.person_id": message.actor.person_id,
            "actor.tenant_id": message.actor.tenant_id,
        }
        missing = [name for name, value in required.items() if not str(value or "").strip()]
        if missing:
            raise BusinessError("MESSAGE_FIELD_REQUIRED", "缺少必填字段：" + ",".join(missing), http_status=400)
        if message.protocol_version != self.config["protocol_version"]:
            raise BusinessError("PROTOCOL_VERSION_MISMATCH", "protocol_version 不匹配", http_status=400)
        if message.capability_dictionary_version != self.config["capability_dictionary_version"]:
            raise BusinessError("CAPABILITY_DICTIONARY_VERSION_MISMATCH", "能力字典版本不匹配", http_status=409)
        if message.registry_version != self.config["registry_version"]:
            raise BusinessError("REGISTRY_VERSION_MISMATCH", "能力登记版本不匹配", http_status=409)
        if message.deadline_at:
            try:
                deadline = _parse_time(message.deadline_at)
            except ValueError:
                raise BusinessError("INVALID_DEADLINE", "deadline_at 不是有效 ISO 8601 时间", http_status=400)
            if datetime.now(timezone.utc) >= deadline:
                raise BusinessError("MESSAGE_DEADLINE_EXCEEDED", "请求已超过 deadline_at", http_status=408)
        if message.route_type == "task.dispatch":
            if not message.context.workflow_instance_id or not message.context.node_id:
                raise BusinessError("WORKFLOW_CONTEXT_REQUIRED", "task.dispatch 必须携带 workflow_instance_id 和 node_id", http_status=400)
        if message.route_type == "flow.callback":
            if not message.parent_message_id or not message.context.task_id:
                raise BusinessError("CALLBACK_CONTEXT_REQUIRED", "flow.callback 必须携带 parent_message_id 和 task_id", http_status=400)
