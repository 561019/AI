from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from adapters.adapter_registry import record_adapter_call
from db import get_conn


def publish_callback(
    *,
    trace_id: str,
    workflow_instance_id: str,
    node_id: str,
    task_id: str,
    reply_type: str,
    status: str,
    result_ref: str = "",
    error_code: str = "",
) -> dict[str, Any]:
    callback_id = f"callback_{uuid4().hex}"
    result = {
        "callback_id": callback_id,
        "trace_id": trace_id,
        "workflow_instance_id": workflow_instance_id,
        "node_id": node_id,
        "task_id": task_id,
        "reply_type": reply_type,
        "status": status,
        "result_ref": result_ref,
        "error_code": error_code,
        "callback_status": "mock_recorded",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO workflow_callback_record (
                callback_id,
                trace_id,
                workflow_instance_id,
                node_id,
                task_id,
                reply_type,
                status,
                result_ref,
                error_code,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                callback_id,
                trace_id,
                workflow_instance_id,
                node_id,
                task_id,
                reply_type,
                status,
                result_ref,
                error_code,
                result["created_at"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    record_adapter_call(
        "workflow_callback",
        "flow.callback",
        result,
    )
    return result
