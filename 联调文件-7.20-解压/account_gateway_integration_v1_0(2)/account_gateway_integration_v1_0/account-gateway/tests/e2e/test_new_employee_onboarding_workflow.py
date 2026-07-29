"""实名账号先挂岗位，再从 L2 经 L1 执行首项受控工作。"""

from helpers import auth_headers, layer_dispatch, permission_command, post
from l1_support import prepare_identity, prepare_probe_contract, unique


def _work(account_id: str, resource_id: str):
    return layer_dispatch(
        account_id=account_id, action="case.process", resource_type="data", resource_id=resource_id,
        data_label="internal", target_service_id="test.permission_probe.v1", command="permission.probe.execute",
    )


def test_new_employee_requires_position_before_first_authorized_work():
    employee, position_id, resource_id = unique("new-employee"), unique("case-position"), unique("case-data")
    created = post(
        "/api/accounts", headers=auth_headers({"user_id": "onboarding-hr", "org_id": "casdoor-e2e-org", "role_list": ["hanhe_admin"]}),
        json={"name": employee, "password": "onboarding-test-only", "displayName": "E2E Employee", "email": f"{employee}@hanhe.local", "roles": ["staff"]},
    )
    assert created.status_code == 201, created.text
    action = permission_command("register_data_action", {"action": "case.process", "description": "process case"})
    assert action.status_code in (200, 201, 409), action.text
    service = permission_command("create_service_call_rule", {
        "source_service": "l1_internal_channel", "target_service": "test.permission_probe.v1", "action": "case.process",
    })
    assert service.status_code in (200, 201, 409), service.text
    assert _work(employee, resource_id).status_code == 403

    prepare_identity(employee, position_id)
    prepare_probe_contract(position_id, action="case.process", resource_type="data", resource_id=resource_id, data_label="internal")
    first_work = _work(employee, resource_id)
    assert first_work.status_code == 200, first_work.text
    assert first_work.json()["result"]["actor_id"] == employee
