"""v2 migration contracts: gateway approval policies are intentionally retired."""

import pytest
import requests

from helpers import E2E_TENANT_ID, auth_headers, get, layer_dispatch, permission_command, post
from l1_support import prepare_identity, prepare_probe_contract, unique


def _admin_headers(account_id: str = "v2-admin") -> dict[str, str]:
    return auth_headers({"user_id": account_id, "org_id": E2E_TENANT_ID, "role_list": ["hanhe_admin", "hanhe_im", "hanhe_dsm"]})


def _probe(account_id: str, action: str, resource_id: str):
    return layer_dispatch(
        account_id=account_id, action=action, resource_type="data", resource_id=resource_id,
        target_service_id="test.permission_probe.v1", command="permission.probe.execute",
    )


def test_runtime_check_uses_l1_and_rejects_illegal_data_state():
    account_id, position_id, resource_id = unique("v2-account"), unique("v2-position"), unique("v2-data")
    prepare_identity(account_id, position_id)
    prepare_probe_contract(position_id, action="read", resource_type="data", resource_id=resource_id)
    assert _probe(account_id, "read", resource_id).status_code == 200
    invalid = layer_dispatch(
        account_id=account_id, action="read", resource_type="data", resource_id=resource_id,
        data_state="not-a-state", target_service_id="test.permission_probe.v1", command="permission.probe.execute",
    )
    assert invalid.status_code == 400
    assert invalid.json()["status"] == "error"
    assert invalid.json()["error"]["code"] == "INVALID_REQUEST"


def test_permission_audits_support_trace_actor_result_and_cursor_filters():
    account_id, position_id, resource_id = unique("audit-account"), unique("audit-position"), unique("audit-data")
    prepare_identity(account_id, position_id)
    prepare_probe_contract(position_id, action="audit.read", resource_type="data", resource_id=resource_id)
    response = _probe(account_id, "audit.read", resource_id)
    assert response.status_code == 200, response.text
    trace_id = response.json()["trace_id"]
    audits = requests.get(
        "http://127.0.0.1:8001/api/permission/audits",
        params={"trace_id": trace_id, "actor_id": account_id, "result": "allow", "after_id": 0, "limit": 10},
        timeout=3,
    )
    assert audits.status_code == 200, audits.text
    rows = audits.json()["audits"]
    assert len(rows) == 1
    assert rows[0]["transfer_id"] == response.json()["transfer_id"]
    assert rows[0]["decision_id"] == response.json()["permission_decision_id"]


def test_security_compliance_events_remain_gateway_audit_events_not_permissions():
    denied = post("/api/audit/events", headers=auth_headers({"user_id": "audit-user", "org_id": E2E_TENANT_ID, "role_list": ["staff"]}), json={"action_type": "security.compliance", "resource_id": "e2e"})
    assert denied.status_code == 403
    accepted = post("/api/audit/events", headers=_admin_headers(), json={"action_type": "security.compliance", "resource_id": "e2e"})
    assert accepted.status_code in (200, 201), accepted.text


def test_tenant_identity_management_remains_in_account_gateway():
    tenant_id = unique("v2-tenant")
    created = post("/api/tenants", headers=_admin_headers(), json={"id": tenant_id, "name": "E2E tenant"})
    assert created.status_code == 201, created.text
    listed = get("/api/tenants", headers=_admin_headers())
    assert listed.status_code == 200
    assert tenant_id in {item["id"] for item in listed.json()["tenants"]}


@pytest.mark.parametrize("path", [
    "/api/approvals",
    "/api/approvals/example/approve",
    "/api/approvals/example/reject",
    "/api/approvals/example/revoke",
    "/api/approval-templates",
])
def test_permission_approval_runtime_interfaces_are_retired(path: str):
    response = post(path, headers=_admin_headers(), json={"subject": "e2e", "object": "e2e", "action": "read"})
    assert response.status_code == 410
    assert response.json()["error"] == "permission_capability_moved"


def test_approval_replacement_is_a_permission_control_fact_with_runtime_effect():
    account_id, position_id, resource_id = unique("approval-account"), unique("approval-position"), unique("approval-resource")
    prepare_identity(account_id, position_id)
    prepare_probe_contract(position_id, action="approved.read", resource_type="data", resource_id=resource_id, grant=False)
    assert _probe(account_id, "approved.read", resource_id).status_code == 403
    grant = permission_command("create_position_standard_resource", {
        "position_id": position_id, "action": "approved.read", "resource_type": "data", "resource_id": resource_id,
        "source_service": "l1_internal_channel", "target_service": "test.permission_probe.v1", "basis": "approval replacement",
    })
    assert grant.status_code == 201, grant.text
    assert _probe(account_id, "approved.read", resource_id).status_code == 200


def test_breakglass_state_does_not_grant_runtime_permission():
    account_id, position_id, resource_id = unique("bg-account"), unique("bg-position"), unique("bg-data")
    prepare_identity(account_id, position_id)
    prepare_probe_contract(position_id, action="breakglass.read", resource_type="data", resource_id=resource_id, grant=False)
    enabled = post("/api/breakglass/enable", headers=_admin_headers("bg-admin"))
    assert enabled.status_code == 200
    denied = _probe(account_id, "breakglass.read", resource_id)
    assert denied.status_code == 403


def test_gateway_auth_validate_is_not_a_permission_allow_fallback():
    response = post("/auth/validate", headers={
        **_admin_headers(), "X-User-ID": "legacy", "X-Resource-Type": "data", "X-Resource-ID": "legacy",
        "X-Resource-Owner-ID": "legacy", "X-Action": "read",
    })
    assert response.status_code in (400, 403, 410, 503)
    assert response.json().get("allow") is not True
