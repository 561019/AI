from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from .store import audit_store


def write_log(
    task_id: str | None,
    actor_id: str | None,
    action: str,
    target: str,
    result: str,
    detail: str,
    layer: str = "system",
) -> dict[str, Any]:
    record = {
        "log_id": "LOG-" + uuid.uuid4().hex[:10].upper(),
        "time": datetime.now().isoformat(timespec="seconds"),
        "task_id": task_id,
        "actor_id": actor_id,
        "layer": layer,
        "action": action,
        "target": target,
        "result": result,
        "detail": detail,
    }
    logs = audit_store.read()
    logs.append(record)
    audit_store.write(logs[-500:])
    return record


def get_logs(task_id: str | None = None) -> list[dict[str, Any]]:
    logs = audit_store.read()
    if task_id is None:
        return logs
    return [x for x in logs if x.get("task_id") in {task_id, None}]
