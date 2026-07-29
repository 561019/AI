from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from adapters.adapter_registry import record_adapter_call


def send_notification(
    *,
    trace_id: str,
    reminder_id: int,
    receiver_role: str,
    receiver_person_id: str,
    receiver_name: str,
    channel: str,
    content: str,
    simulate_failure: bool = False,
) -> dict[str, Any]:
    notification_id = f"notify_{uuid4().hex}"
    delivered = not simulate_failure and channel != "mock_fail"
    result = {
        "notification_id": notification_id,
        "trace_id": trace_id,
        "reminder_id": reminder_id,
        "receiver_role": receiver_role,
        "receiver_person_id": receiver_person_id,
        "receiver_name": receiver_name,
        "channel": channel,
        "delivered": delivered,
        "delivery_status": "送达成功" if delivered else "送达失败",
        "reason": (
            "Mock 通知通道送达成功"
            if delivered
            else "Mock 通知通道模拟发送失败"
        ),
        "sent_at": datetime.now().isoformat(timespec="seconds"),
    }
    record_adapter_call(
        "notification_channel",
        "notification.send",
        {
            "notification_id": notification_id,
            "trace_id": trace_id,
            "reminder_id": reminder_id,
            "delivered": delivered,
            "channel": channel,
        },
    )
    return result
