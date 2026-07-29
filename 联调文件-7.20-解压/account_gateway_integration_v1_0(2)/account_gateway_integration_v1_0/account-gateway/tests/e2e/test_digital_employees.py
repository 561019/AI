import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

from helpers import get, post, request, sign_jwt


JWT_SECRET = "change-me"
ORG_ID = "casdoor-e2e-org"


def normal_token(user_id, role_list=None, org_id=ORG_ID):
    return sign_jwt(
        {"user_id": user_id, "org_id": org_id, "role_list": role_list or ["staff"]},
        secret=JWT_SECRET,
    )


def admin_token(user_id="digital-admin", org_id=ORG_ID):
    return normal_token(user_id, ["hanhe_admin"], org_id=org_id)


def digital_token(user_id, parent_user_id, role_list=None, org_id=ORG_ID, token_version=None):
    claims = {
        "user_id": user_id,
        "org_id": org_id,
        "role_list": role_list or ["tool_runner"],
        "is_digital": True,
        "parent_user_id": parent_user_id,
    }
    if token_version is not None:
        claims["token_version"] = token_version
    return sign_jwt(
        claims,
        secret=JWT_SECRET,
    )


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def unique_name(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def create_employee(owner_id, name=None, roles=None, token=None, org_id=ORG_ID):
    employee_name = name or unique_name("agent")
    response = post(
        "/api/digital-employees",
        headers=auth_header(token or normal_token(owner_id, org_id=org_id)),
        json={"name": employee_name, "roles": roles or ["tool_runner"]},
    )
    return response, employee_name


def jwt_payload(token):
    payload = token.split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def validate_headers(token, user_id, resource_type, action, owner_id):
    return {
        **auth_header(token),
        "X-User-ID": user_id,
        "X-Resource-Type": resource_type,
        "X-Action": action,
        "X-Resource-Owner-ID": owner_id,
    }


def validate_headers_with_extra(token, user_id, resource_type, action, owner_id, **extra):
    headers = validate_headers(token, user_id, resource_type, action, owner_id)
    headers.update(extra)
    return headers


def test_list_digital_employees_empty_owner_returns_empty_array():
    owner_id = unique_name("empty-owner")

    response = get(
        "/api/digital-employees",
        headers=auth_header(normal_token(owner_id)),
    )

    assert response.status_code == 200
    assert response.json()["digital_employees"] == []


def test_create_digital_employee_returns_201_and_digital_jwt_claims():
    owner_id = unique_name("owner")
    response, employee_name = create_employee(owner_id, roles=["tool_runner", "assistant"])

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == employee_name
    assert body["parent_user_id"] == owner_id
    assert body["roles"] == ["tool_runner", "assistant"]
    assert body["token"]

    claims = jwt_payload(body["token"])
    assert claims["user_id"] == employee_name
    assert claims["org_id"] == ORG_ID
    assert claims["role_list"] == ["tool_runner", "assistant"]
    assert claims["is_digital"] is True
    assert claims["parent_user_id"] == owner_id
    assert body["tenant_id"] == ORG_ID


def test_list_digital_employees_returns_only_owned_records():
    owner_id = unique_name("owner")
    other_owner_id = unique_name("owner")
    owned_response, owned_name = create_employee(owner_id)
    other_response, other_name = create_employee(other_owner_id)

    assert owned_response.status_code == 201
    assert other_response.status_code == 201

    response = get(
        "/api/digital-employees",
        headers=auth_header(normal_token(owner_id)),
    )

    assert response.status_code == 200
    employees = response.json()["digital_employees"]
    names = [employee["name"] for employee in employees]
    assert owned_name in names
    assert other_name not in names


def test_get_single_digital_employee_returns_owned_record():
    owner_id = unique_name("owner")
    create_response, employee_name = create_employee(owner_id, roles=["tool_runner"])
    assert create_response.status_code == 201

    response = get(
        f"/api/digital-employees/{employee_name}",
        headers=auth_header(normal_token(owner_id)),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == employee_name
    assert body["parent_user_id"] == owner_id
    assert body["roles"] == ["tool_runner"]


def test_delete_digital_employee_returns_204_and_removes_record():
    owner_id = unique_name("owner")
    create_response, employee_name = create_employee(owner_id)
    assert create_response.status_code == 201

    delete_response = request(
        "DELETE",
        f"/api/digital-employees/{employee_name}",
        headers=auth_header(normal_token(owner_id)),
    )

    assert delete_response.status_code == 204

    get_response = get(
        f"/api/digital-employees/{employee_name}",
        headers=auth_header(normal_token(owner_id)),
    )
    assert get_response.status_code == 404


def test_digital_employee_validate_denies_data_access():
    parent_id = unique_name("parent")
    employee_id = unique_name("agent")
    token = digital_token(employee_id, parent_id)

    response = post(
        "/auth/validate",
        headers=validate_headers(token, employee_id, "data", "read", parent_id),
        json={
            "user_id": employee_id,
            "resource_type": "data",
            "action": "read",
            "owner_id": parent_id,
        },
    )

    assert response.status_code == 200
    assert response.json()["allow"] is False
    assert response.json()["reason"] == "digital_employee_no_data_access"


def test_digital_employee_validate_allows_parent_owned_tool_access():
    parent_id = unique_name("parent")
    employee_id = unique_name("agent")
    token = digital_token(employee_id, parent_id)

    response = post(
        "/auth/validate",
        headers=validate_headers(token, employee_id, "tool", "use", parent_id),
        json={
            "user_id": employee_id,
            "resource_type": "tool",
            "action": "use",
            "owner_id": parent_id,
        },
    )

    assert response.status_code == 200
    assert response.json()["allow"] is True


def test_digital_employee_cannot_create_another_digital_employee():
    parent_id = unique_name("parent")
    employee_id = unique_name("agent")
    token = digital_token(employee_id, parent_id)

    response = post(
        "/api/digital-employees",
        headers=auth_header(token),
        json={"name": unique_name("nested-agent"), "roles": ["tool_runner"]},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "digital_employee_cannot_create_digital"


def test_admin_can_create_digital_employee_for_another_parent():
    parent_id = unique_name("owner")
    employee_name = unique_name("admin-agent")

    response = post(
        "/api/digital-employees",
        headers=auth_header(admin_token()),
        json={"name": employee_name, "parent_user_id": parent_id, "roles": ["tool_runner"]},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == employee_name
    assert body["parent_user_id"] == parent_id
    assert jwt_payload(body["token"])["parent_user_id"] == parent_id


def test_digital_employee_isolated_by_tenant_for_admin_and_validate():
    org_a = unique_name("org-a")
    org_b = unique_name("org-b")
    owner_id = unique_name("owner")
    create_response, employee_name = create_employee(owner_id, org_id=org_a)
    assert create_response.status_code == 201

    list_response = get(
        "/api/digital-employees",
        headers=auth_header(admin_token("admin-b", org_id=org_b)),
    )
    assert list_response.status_code == 200
    assert list_response.json()["digital_employees"] == []

    for method, path, body in [
        ("GET", f"/api/digital-employees/{employee_name}", None),
        ("POST", f"/api/digital-employees/{employee_name}/disable", None),
        ("POST", f"/api/digital-employees/{employee_name}/rotate-token", None),
        ("POST", f"/api/digital-employees/{employee_name}/execution-mode", {"execution_mode": "scope_reject"}),
        ("DELETE", f"/api/digital-employees/{employee_name}", None),
    ]:
        response = request(
            method,
            path,
            headers=auth_header(admin_token("admin-b", org_id=org_b)),
            json=body,
        )
        assert response.status_code == 404

    wrong_tenant_token = digital_token(
        employee_name,
        owner_id,
        org_id=org_b,
        token_version=1,
    )
    validate_response = post(
        "/auth/validate",
        headers=validate_headers(wrong_tenant_token, employee_name, "tool", "use", owner_id),
    )
    assert validate_response.status_code == 200
    assert validate_response.json() == {
        "allow": False,
        "reason": "digital_employee_token_revoked",
    }


def test_digital_employee_execution_modes_require_confirmation_and_reject_scope():
    owner_id = unique_name("owner")
    employee_name = unique_name("mode-agent")

    created = post(
        "/api/digital-employees",
        headers=auth_header(normal_token(owner_id)),
        json={
            "name": employee_name,
            "roles": ["tool_runner"],
            "execution_mode": "require_confirmation",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["execution_mode"] == "require_confirmation"
    token = body["token"]

    missing_confirmation = post(
        "/auth/validate",
        headers=validate_headers(token, employee_name, "tool", "use", owner_id),
    )
    assert missing_confirmation.status_code == 200
    assert missing_confirmation.json() == {
        "allow": False,
        "reason": "digital_employee_confirmation_required",
    }

    confirmed = post(
        "/auth/validate",
        headers=validate_headers_with_extra(
            token,
            employee_name,
            "tool",
            "use",
            owner_id,
            **{"X-Digital-Confirmed-By": owner_id},
        ),
    )
    assert confirmed.status_code == 200
    assert confirmed.json() == {
        "allow": True,
        "policy_id": "digital_employee_parent_tool",
    }

    updated = post(
        f"/api/digital-employees/{employee_name}/execution-mode",
        headers=auth_header(normal_token(owner_id)),
        json={"execution_mode": "scope_reject"},
    )
    assert updated.status_code == 200
    assert updated.json() == {"name": employee_name, "execution_mode": "scope_reject"}

    other_owner = post(
        "/auth/validate",
        headers=validate_headers(token, employee_name, "tool", "use", unique_name("other-owner")),
    )
    assert other_owner.status_code == 200
    assert other_owner.json() == {
        "allow": False,
        "reason": "digital_employee_scope_rejected",
    }

    parent_owned = post(
        "/auth/validate",
        headers=validate_headers(token, employee_name, "tool", "use", owner_id),
    )
    assert parent_owned.status_code == 200
    assert parent_owned.json() == {
        "allow": True,
        "policy_id": "digital_employee_parent_tool",
    }


def test_expired_digital_employee_cannot_validate_or_rotate_token():
    owner_id = unique_name("owner")
    employee_name = unique_name("expired-agent")
    expired_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    created = post(
        "/api/digital-employees",
        headers=auth_header(normal_token(owner_id)),
        json={
            "name": employee_name,
            "roles": ["tool_runner"],
            "expires_at": expired_at,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["expires_at"] == expired_at

    validate_response = post(
        "/auth/validate",
        headers=validate_headers(body["token"], employee_name, "tool", "use", owner_id),
    )
    assert validate_response.status_code == 200
    assert validate_response.json() == {
        "allow": False,
        "reason": "digital_employee_expired",
    }

    rotated = post(
        f"/api/digital-employees/{employee_name}/rotate-token",
        headers=auth_header(normal_token(owner_id)),
    )
    assert rotated.status_code == 409
    assert rotated.json() == {"error": "digital_employee_expired"}


def test_digital_employee_lifecycle_uses_default_role_and_writes_audit():
    owner_id = unique_name("audit-owner")
    employee_name = unique_name("audit-agent")
    owner_headers = auth_header(normal_token(owner_id))

    created = post(
        "/api/digital-employees",
        headers=owner_headers,
        json={"name": employee_name},
    )
    assert created.status_code == 201
    assert created.json()["roles"] == ["digital_employee"]
    assert jwt_payload(created.json()["token"])["role_list"] == ["digital_employee"]

    mode = post(
        f"/api/digital-employees/{employee_name}/execution-mode",
        headers=owner_headers,
        json={"execution_mode": "require_confirmation"},
    )
    assert mode.status_code == 200
    assert post(f"/api/digital-employees/{employee_name}/rotate-token", headers=owner_headers).status_code == 200
    assert post(f"/api/digital-employees/{employee_name}/disable", headers=owner_headers).status_code == 200
    assert request("DELETE", f"/api/digital-employees/{employee_name}", headers=owner_headers).status_code == 204

    logs = get(
        f"/api/audit/logs?actor_id={owner_id}&resource_id={employee_name}&limit=20",
        headers=auth_header(admin_token("digital-audit-admin")),
    )
    assert logs.status_code == 200
    actions = {item["action_type"] for item in logs.json()["logs"]}
    assert {
        "digital_employees.create",
        "digital_employees.execution_mode",
        "digital_employees.rotate_token",
        "digital_employees.disable",
        "digital_employees.delete",
    }.issubset(actions)
