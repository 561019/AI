import time

from helpers import E2E_TENANT_ID, auth_headers, permission_command, post


def unique(prefix: str) -> str:
    return f"{prefix}-{time.time_ns()}"


def prepare_identity(account_id: str, position_id: str, *, tenant_id: str = E2E_TENANT_ID) -> None:
    im_headers = auth_headers(
        {"user_id": "e2e-im", "org_id": tenant_id, "role_list": ["hanhe_im"]}
    )
    position = post(
        "/api/positions",
        headers=im_headers,
        json={"id": position_id, "title": "E2E 业务岗位", "department_id": "e2e"},
    )
    assert position.status_code == 201, position.text
    assignment = post(
        "/api/person-position-assignments",
        headers=im_headers,
        json={"person_id": account_id, "user_id": account_id, "position_id": position_id},
    )
    assert assignment.status_code == 201, assignment.text
    permission_position = permission_command(
        "create_position", {"id": position_id, "title": "E2E 业务岗位"}, organization=True, tenant_id=tenant_id
    )
    assert permission_position.status_code == 201, permission_position.text


def prepare_identity_runtime_contract(position_id: str, *, grant: bool, tenant_id: str = E2E_TENANT_ID) -> None:
    action = permission_command(
        "register_data_action",
        {"action": "identity.context.read_self", "description": "读取本人身份上下文"},
        tenant_id=tenant_id,
    )
    assert action.status_code in (200, 201, 409), action.text
    relation = permission_command(
        "create_service_call_rule",
        {
            "source_service": "l1_internal_channel",
            "target_service": "account.identity_context.v1",
            "action": "identity.context.read_self",
        },
        tenant_id=tenant_id,
    )
    assert relation.status_code in (200, 201, 409), relation.text
    if not grant:
        return
    standard = permission_command(
        "create_position_standard_resource",
        {
            "position_id": position_id,
            "action": "identity.context.read_self",
            "data_label": "normal",
            "data_states": ["active"],
            "source_service": "l1_internal_channel",
            "target_service": "account.identity_context.v1",
            "resource_type": "identity_context",
            "resource_id": "*",
            "basis": "E2E L1 机制直达测试",
        },
        tenant_id=tenant_id,
    )
    assert standard.status_code == 201, standard.text


def prepare_probe_contract(
    position_id: str,
    *,
    action: str,
    resource_type: str,
    resource_id: str = "*",
    data_label: str = "normal",
    data_states: list[str] | None = None,
    grant: bool = True,
    tenant_id: str = E2E_TENANT_ID,
) -> None:
    """Register one L2 -> L1 test action and, optionally, its position grant."""
    registered_action = permission_command(
        "register_data_action", {"action": action, "description": f"E2E {action}"}, tenant_id=tenant_id
    )
    assert registered_action.status_code in (200, 201, 409), registered_action.text
    relation = permission_command(
        "create_service_call_rule",
        {
            "source_service": "l1_internal_channel",
            "target_service": "test.permission_probe.v1",
            "action": action,
        }, tenant_id=tenant_id,
    )
    assert relation.status_code in (200, 201, 409), relation.text
    if not grant:
        return
    standard = permission_command(
        "create_position_standard_resource",
        {
            "position_id": position_id,
            "action": action,
            "data_label": data_label,
            "data_states": data_states or ["active"],
            "source_service": "l1_internal_channel",
            "target_service": "test.permission_probe.v1",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "basis": "E2E L1 permission-probe test",
        }, tenant_id=tenant_id,
    )
    assert standard.status_code == 201, standard.text
