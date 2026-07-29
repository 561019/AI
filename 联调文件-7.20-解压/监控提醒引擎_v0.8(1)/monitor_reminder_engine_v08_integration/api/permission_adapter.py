from __future__ import annotations

from typing import Any

from adapters.mock_permission_management import (
    MOCK_MODULE_POLICIES,
    MOCK_PERMISSION_MODE,
    decide_permission,
)


def check_permission(
    *,
    source_module: str,
    operator_id: str,
    permission_token: str,
    required_permission: str,
    body_source_module: str = "",
    body_operator_id: str = "",
) -> dict[str, Any]:
    """
    兼容旧调用签名。正式权限判定由 Mock L1.1 适配器承担。
    后续切换真实权限服务时，仅替换 adapters 下的实现。
    """
    return decide_permission(
        source_module=source_module,
        operator_id=operator_id,
        permission_token=permission_token,
        required_permission=required_permission,
        body_source_module=body_source_module,
        body_operator_id=body_operator_id,
    )
