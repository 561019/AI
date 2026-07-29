from __future__ import annotations

from typing import Any
from uuid import uuid4

from adapters.adapter_registry import record_adapter_call


MOCK_PERMISSION_MODE = "mock"

MOCK_MODULE_POLICIES: dict[str, dict[str, Any]] = {
    "workflow_engine_demo": {
        "token": "WF_DEMO_TOKEN_V07",
        "permissions": {
            "monitor_item:create",
            "monitor_item:read",
            "monitor_item:update",
            "monitor_item:enable",
            "monitor_item:pause",
            "monitor_item:resume",
            "monitor_item:disable",
            "reminder:escalate",
            "reminder:recover",
            "trace:read",
            "layer_message:dispatch",
        },
    },
    "rule_engine_demo": {
        "token": "RULE_DEMO_TOKEN_V07",
        "permissions": {
            "reminder:trigger",
            "trace:read",
        },
    },
    "account_gateway_demo": {
        "token": "ACCOUNT_DEMO_TOKEN_V07",
        "permissions": {
            "reminder:confirm",
            "trace:read",
        },
    },
    "system_admin_demo": {
        "token": "ADMIN_DEMO_TOKEN_V07",
        "permissions": {
            "monitor_item:read",
            "trace:read",
            "audit:read",
            "capability:read",
            "adapter:read",
        },
    },
}


def decide_permission(
    *,
    source_module: str,
    operator_id: str,
    permission_token: str,
    required_permission: str,
    body_source_module: str = "",
    body_operator_id: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "allowed": False,
        "mode": MOCK_PERMISSION_MODE,
        "permission": required_permission,
        "source_module": source_module,
        "operator_id": operator_id,
        "decision_id": f"perm_dec_{uuid4().hex}",
        "obligations": [
            "trace_required",
            "audit_required",
            "least_data",
        ],
        "reason": "",
    }

    if not source_module:
        result["reason"] = "缺少请求头 X-Source-Module"
    elif not operator_id:
        result["reason"] = "缺少请求头 X-Operator-ID"
    elif not permission_token:
        result["reason"] = "缺少请求头 X-Permission-Token"
    else:
        policy = MOCK_MODULE_POLICIES.get(source_module)
        if policy is None:
            result["reason"] = "来源模块未登记到 Mock 权限策略"
        elif permission_token != policy["token"]:
            result["reason"] = "权限令牌无效"
        elif body_source_module and body_source_module != source_module:
            result["reason"] = (
                "请求头 X-Source-Module 与请求体 source_module 不一致"
            )
        elif body_operator_id and body_operator_id != operator_id:
            result["reason"] = (
                "请求头 X-Operator-ID 与请求体 operator_id 不一致"
            )
        elif required_permission not in policy["permissions"]:
            result["reason"] = "当前来源模块无权执行该操作"
        else:
            result["allowed"] = True
            result["reason"] = "Mock 权限判定通过"

    record_adapter_call(
        "permission_management_1_1",
        "permission.decide",
        {
            "decision_id": result["decision_id"],
            "permission": required_permission,
            "allowed": result["allowed"],
            "source_module": source_module,
            "operator_id": operator_id,
        },
    )
    return result
