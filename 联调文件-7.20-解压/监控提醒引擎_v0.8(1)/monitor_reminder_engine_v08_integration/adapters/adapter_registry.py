from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from threading import Lock
from typing import Any


_LOCK = Lock()

_STATE: dict[str, dict[str, Any]] = {
    "data_module_1_7": {
        "service_code": "l1.data",
        "mode": "mock",
        "status": "enabled",
        "call_count": 0,
        "last_action": "",
        "last_called_at": "",
        "last_evidence": {},
    },
    "account_gateway_1_8": {
        "service_code": "l1.account_gateway",
        "mode": "mock",
        "status": "enabled",
        "call_count": 0,
        "last_action": "",
        "last_called_at": "",
        "last_evidence": {},
    },
    "permission_management_1_1": {
        "service_code": "l1.permission_management",
        "mode": "mock",
        "status": "enabled",
        "call_count": 0,
        "last_action": "",
        "last_called_at": "",
        "last_evidence": {},
    },
    "security_compliance_1_9": {
        "service_code": "l1.security_compliance",
        "mode": "mock",
        "status": "enabled",
        "call_count": 0,
        "last_action": "",
        "last_called_at": "",
        "last_evidence": {},
    },
    "notification_channel": {
        "service_code": "l4.notification_channel",
        "mode": "mock",
        "status": "enabled",
        "call_count": 0,
        "last_action": "",
        "last_called_at": "",
        "last_evidence": {},
    },
    "workflow_callback": {
        "service_code": "l2.workflow_execution",
        "mode": "mock",
        "status": "enabled",
        "call_count": 0,
        "last_action": "",
        "last_called_at": "",
        "last_evidence": {},
    },
}


def record_adapter_call(
    adapter_name: str,
    action: str,
    evidence: dict[str, Any] | None = None,
) -> None:
    with _LOCK:
        state = _STATE.setdefault(
            adapter_name,
            {
                "service_code": adapter_name,
                "mode": "mock",
                "status": "enabled",
                "call_count": 0,
                "last_action": "",
                "last_called_at": "",
                "last_evidence": {},
            },
        )
        state["call_count"] = int(state.get("call_count", 0)) + 1
        state["last_action"] = action
        state["last_called_at"] = datetime.now().isoformat(
            timespec="seconds"
        )
        state["last_evidence"] = deepcopy(evidence or {})


def get_adapter_status() -> dict[str, dict[str, Any]]:
    with _LOCK:
        return deepcopy(_STATE)
