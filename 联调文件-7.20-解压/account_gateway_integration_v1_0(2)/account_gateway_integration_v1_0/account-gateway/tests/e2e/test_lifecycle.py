import os
import sqlite3
import time
from pathlib import Path

import requests

from helpers import get, post, request, sign_jwt


CASDOOR_URL = os.environ.get("CASDOOR_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
JWT_SECRET = "change-me"
ORG_ID = "casdoor-e2e-org"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DB = PROJECT_ROOT / ".e2e-data" / "audit.db"


def test_create_account_is_visible_in_casdoor():
    name = unique_name("create")

    response = create_account(name)

    assert response.status_code == 201
    assert casdoor_user(name)["name"] == name


def test_account_create_requires_admin_or_operator():
    name = unique_name("forbidden")

    unauthenticated = post(
        "/api/accounts",
        json=account_payload(name),
    )
    assert unauthenticated.status_code == 401

    forbidden = post(
        "/api/accounts",
        headers=auth_headers("staff-user", ["staff"]),
        json=account_payload(name),
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"] == "admin_or_operator_only"


def test_operator_can_create_account():
    name = unique_name("operator")

    response = post(
        "/api/accounts",
        headers=auth_headers("operator-user", ["operator"]),
        json=account_payload(name),
    )

    assert response.status_code == 201
    assert casdoor_user(name)["name"] == name


def test_regular_user_can_only_read_self():
    name = unique_name("self")
    other_name = unique_name("other")
    create_account(name).raise_for_status()
    create_account(other_name).raise_for_status()

    own = get(
        f"/api/accounts?name={name}",
        headers=auth_headers(name, ["staff"]),
    )
    assert own.status_code == 200
    assert [account["name"] for account in own.json()] == [name]

    implicit_own = get(
        "/api/accounts",
        headers=auth_headers(name, ["staff"]),
    )
    assert implicit_own.status_code == 200
    assert [account["name"] for account in implicit_own.json()] == [name]

    other = get(
        f"/api/accounts?name={other_name}",
        headers=auth_headers(name, ["staff"]),
    )
    assert other.status_code == 403


def test_accounts_are_isolated_by_tenant_even_for_admin():
    tenant_a = unique_name("tenant-a")
    tenant_b = unique_name("tenant-b")
    name = unique_name("tenant-account")

    created = create_account(name, org_id=tenant_a)
    assert created.status_code == 201
    assert created.json()["properties"]["tenant_id"] == tenant_a

    list_b = get("/api/accounts", headers=admin_headers("tenant-b-admin", org_id=tenant_b))
    assert list_b.status_code == 200
    assert name not in [account["name"] for account in list_b.json()]

    get_b = get(
        f"/api/accounts?name={name}",
        headers=admin_headers("tenant-b-admin", org_id=tenant_b),
    )
    assert get_b.status_code == 200
    assert get_b.json() == []

    update_b = request(
        "PATCH",
        f"/api/accounts?name={name}",
        headers=admin_headers("tenant-b-admin", org_id=tenant_b),
        json={"status": "inactive"},
    )
    assert update_b.status_code == 404
    assert update_b.json()["error"] == "account_not_found"

    delete_b = request(
        "DELETE",
        f"/api/accounts?name={name}",
        headers=admin_headers("tenant-b-admin", org_id=tenant_b),
    )
    assert delete_b.status_code == 404
    assert delete_b.json()["error"] == "account_not_found"

    get_a = get(
        f"/api/accounts?name={name}",
        headers=admin_headers("tenant-a-admin", org_id=tenant_a),
    )
    assert get_a.status_code == 200
    assert [account["name"] for account in get_a.json()] == [name]


def test_disable_account_sets_casdoor_user_inactive():
    name = unique_name("disable")
    create_account(name).raise_for_status()

    response = request(
        "PATCH",
        f"/api/accounts?name={name}",
        headers=admin_headers(),
        json={"status": "inactive"},
    )

    assert response.status_code == 200
    assert casdoor_user(name)["isForbidden"] is True


def test_delete_with_data_returns_conflict():
    create_account("user_li").raise_for_status()

    response = request("DELETE", "/api/accounts?name=user_li", headers=admin_headers())

    assert response.status_code == 409
    assert response.json()["resources"] == [
        {"resource_id": "dataset_001", "owner_id": "user_li"}
    ]
    assert casdoor_user("user_li")["name"] == "user_li"


def test_delete_clean_removes_casdoor_user():
    name = unique_name("clean")
    create_account(name).raise_for_status()

    before_handover = request("DELETE", f"/api/accounts?name={name}", headers=admin_headers())
    assert before_handover.status_code == 409
    assert before_handover.json() == {
        "error": "account handover not confirmed",
        "lifecycle_state": "active",
    }

    freeze = post(f"/api/accounts/{name}/freeze", headers=admin_headers())
    assert freeze.status_code == 200
    assert freeze.json()["isForbidden"] is True
    assert freeze.json()["properties"]["lifecycle_state"] == "frozen"
    assert freeze.json()["properties"]["handover_confirmed"] == "false"

    still_blocked = request("DELETE", f"/api/accounts?name={name}", headers=admin_headers())
    assert still_blocked.status_code == 409
    assert still_blocked.json() == {
        "error": "account handover not confirmed",
        "lifecycle_state": "frozen",
    }

    confirm = post(f"/api/accounts/{name}/handover-confirm", headers=admin_headers())
    assert confirm.status_code == 200
    assert confirm.json()["properties"]["handover_confirmed"] == "true"
    assert confirm.json()["properties"]["lifecycle_state"] == "handover_confirmed"

    response = request("DELETE", f"/api/accounts?name={name}", headers=admin_headers())

    assert response.status_code == 204
    assert casdoor_user(name) is None


def test_freeze_account_changes_identity_lifecycle_without_writing_permission_assets():
    name = unique_name("identity-freeze")
    create_account(name).raise_for_status()

    freeze = post(f"/api/accounts/{name}/freeze", headers=admin_headers("freeze-admin"))
    assert freeze.status_code == 200
    properties = freeze.json()["properties"]
    assert properties["lifecycle_state"] == "frozen"
    assert properties["frozen_by"] == "freeze-admin"
    assert "frozen_resources" not in properties
    assert "frozen_data_records" not in properties
    assert "frozen_digital_employees" not in properties

    confirm = post(f"/api/accounts/{name}/handover-confirm", headers=admin_headers("freeze-admin"))
    assert confirm.status_code == 200
    assert request("DELETE", f"/api/accounts?name={name}", headers=admin_headers("freeze-admin")).status_code == 204


def _legacy_asset_freeze_scenario_archived_with_permission_boundary():
    name = unique_name("asset-freeze")
    person = unique_name("person-freeze")
    position = unique_name("pos-freeze")
    resource_id = unique_name("skill-freeze")
    data_id = unique_name("data-freeze")
    digital_id = unique_name("agent-freeze")
    create_account(name).raise_for_status()

    digital = post(
        "/api/digital-employees",
        headers=auth_headers(name, ["staff"]),
        json={"name": digital_id, "roles": ["tool_runner"]},
    )
    assert digital.status_code == 201
    digital_token = digital.json()["token"]

    command(
        "/api/org/commands",
        auth_headers("freeze-im", ["hanhe_im"]),
        "create_position",
        {"id": position, "title": "Asset Owner", "department_id": "dep-freeze", "tenant_id": ORG_ID},
    )
    command(
        "/api/org/commands",
        auth_headers("freeze-im", ["hanhe_im"]),
        "assign_person_position",
        {"person_id": person, "user_id": name, "position_id": position, "tenant_id": ORG_ID},
    )
    command(
        "/api/permissions/commands",
        auth_headers("freeze-dsm", ["hanhe_dsm"]),
        "create_position_standard_resource",
        {"position_id": position, "resource_type": "data", "resource_id": data_id, "action": "fetch", "owner_user_id": name},
    )
    command(
        "/api/permissions/commands",
        auth_headers(name, ["staff"]),
        "create_resource",
        {
            "id": resource_id,
            "name": "handover skill",
            "resource_type": "skill",
            "owner_person_id": person,
            "owner_user_id": name,
            "owner_position_id": position,
            "department_id": "dep-freeze",
            "tenant_id": ORG_ID,
        },
    )
    command(
        "/api/permissions/commands",
        auth_headers(name, ["staff"]),
        "register_data",
        {
            "id": data_id,
            "title": "handover data",
            "source_type": "conversation",
            "owner_person_id": person,
            "owner_user_id": name,
            "tenant_id": ORG_ID,
            "business_tags": ["handover"],
            "storage_refs": ["sqlite://handover"],
            "allowed_actions": ["fetch"],
            "basis": "offboarding handover",
        },
    )

    before_resource = validate(name, "skill", resource_id, "use", name, person, position)
    assert before_resource.status_code == 200
    assert before_resource.json()["allow"] is True

    before_data = validate(name, "data", data_id, "fetch", name, person, position)
    assert before_data.status_code == 200
    assert before_data.json()["allow"] is True

    freeze = post(f"/api/accounts/{name}/freeze", headers=admin_headers("freeze-admin"))
    assert freeze.status_code == 200
    assert freeze.json()["properties"]["frozen_resources"] == "1"
    assert freeze.json()["properties"]["frozen_data_records"] == "1"
    assert freeze.json()["properties"]["frozen_digital_employees"] == "1"

    frozen_resources = get("/api/permissions/snapshot?status=frozen", headers=auth_headers("freeze-dsm", ["hanhe_dsm"]))
    assert frozen_resources.status_code == 200
    resource_rows = {item["id"]: item for item in frozen_resources.json()["resources"]}
    data_rows = {item["id"]: item for item in frozen_resources.json()["data_records"]}
    assert resource_id in resource_rows
    assert data_id in data_rows
    assert resource_rows[resource_id]["asset_pool"] == "offboarding"
    assert resource_rows[resource_id]["locked_by"] == "freeze-admin"
    assert resource_rows[resource_id]["locked_at"]
    assert data_rows[data_id]["asset_pool"] == "offboarding"
    assert data_rows[data_id]["locked_by"] == "freeze-admin"
    assert data_rows[data_id]["locked_at"]

    view_start = audit_log_high_watermark()
    offboarding_assets = get(
        f"/api/accounts/{name}/offboarding-assets",
        headers=admin_headers("freeze-admin"),
    )
    assert offboarding_assets.status_code == 200
    body = offboarding_assets.json()
    assert body["user_id"] == name
    assert body["tenant_id"] == ORG_ID
    assert [item["id"] for item in body["resources"]] == [resource_id]
    assert body["resources"][0]["asset_pool"] == "offboarding"
    assert [item["id"] for item in body["data_records"]] == [data_id]
    assert body["data_records"][0]["locked_by"] == "freeze-admin"
    assert [item["name"] for item in body["digital_employees"]] == [digital_id]
    assert body["digital_employees"][0]["status"] == "disabled"
    assert ("accounts.offboarding_assets_view", name, "allow") in audit_actions_after(view_start)

    after_resource = validate(name, "skill", resource_id, "use", name, person, position)
    assert after_resource.status_code == 200
    assert after_resource.json() == {"allow": False}

    after_data = validate(name, "data", data_id, "fetch", name, person, position)
    assert after_data.status_code == 200
    assert after_data.json() == {"allow": False, "reason": "data_record_inactive"}

    after_digital = post(
        "/auth/validate",
        headers={
            "Authorization": f"Bearer {digital_token}",
            "X-User-ID": digital_id,
            "X-Resource-Type": "tool",
            "X-Resource-ID": "handover-tool",
            "X-Resource-Owner-ID": name,
            "X-Action": "use",
            "X-Tenant-ID": ORG_ID,
        },
    )
    assert after_digital.status_code == 200
    assert after_digital.json() == {"allow": False, "reason": "digital_employee_token_revoked"}

    confirm = post(
        f"/api/accounts/{name}/handover-confirm",
        headers=admin_headers("freeze-admin"),
        json={"handover_to_user_id": "successor-user", "note": "asset pool checked"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["properties"]["handover_to_user_id"] == "successor-user"
    assert confirm.json()["properties"]["handover_note"] == "asset pool checked"
    deleted = request("DELETE", f"/api/accounts?name={name}", headers=admin_headers("freeze-admin"))
    assert deleted.status_code == 204


def test_account_create_update_delete_write_audit():
    name = unique_name("audit")
    start_id = audit_log_high_watermark()

    create = create_account(name)
    assert create.status_code == 201

    update = request(
        "PATCH",
        f"/api/accounts?name={name}",
        headers=admin_headers("account-audit-admin"),
        json={"displayName": "Audited Account", "status": "active"},
    )
    assert update.status_code == 200

    freeze = post(
        f"/api/accounts/{name}/freeze",
        headers=admin_headers("account-audit-admin"),
    )
    assert freeze.status_code == 200

    confirm = post(
        f"/api/accounts/{name}/handover-confirm",
        headers=admin_headers("account-audit-admin"),
    )
    assert confirm.status_code == 200

    delete = request(
        "DELETE",
        f"/api/accounts?name={name}",
        headers=admin_headers("account-audit-admin"),
    )
    assert delete.status_code == 204

    actions = audit_actions_after(start_id)
    assert ("accounts.create", name, "allow") in actions
    assert ("accounts.update", name, "allow") in actions
    assert ("accounts.freeze", name, "allow") in actions
    assert ("accounts.handover_confirm", name, "allow") in actions
    assert ("accounts.delete", name, "allow") in actions


def test_delete_with_data_writes_deny_audit():
    create_account("user_li").raise_for_status()
    start_id = audit_log_high_watermark()

    response = request(
        "DELETE",
        "/api/accounts?name=user_li",
        headers=admin_headers("account-block-admin"),
    )

    assert response.status_code == 409
    actions = audit_actions_after(start_id)
    assert ("accounts.delete", "user_li", "deny") in actions


def create_account(name: str, org_id: str = ORG_ID) -> requests.Response:
    return post(
        "/api/accounts",
        headers=admin_headers(org_id=org_id),
        json=account_payload(name),
    )


def command(path: str, headers: dict[str, str], action: str, payload: dict) -> dict:
    response = post(path, headers=headers, json={"action": action, "payload": payload})
    assert response.status_code in (200, 201), response.text
    return response.json()


def validate(
    user_id: str,
    resource_type: str,
    resource_id: str,
    action: str,
    owner_user_id: str,
    person_id: str,
    position_id: str,
) -> requests.Response:
    return post(
        "/auth/validate",
        headers={
            **auth_headers(user_id, ["staff"]),
            "X-User-ID": user_id,
            "X-Resource-Type": resource_type,
            "X-Resource-ID": resource_id,
            "X-Resource-Owner-ID": owner_user_id,
            "X-Action": action,
            "X-Person-ID": person_id,
            "X-Position-ID": position_id,
            "X-Tenant-ID": ORG_ID,
        },
    )


def account_payload(name: str) -> dict:
    return {
        "name": name,
        "password": "123",
        "displayName": name.replace("-", " ").title(),
        "email": f"{name}@hanhe.local",
        "roles": ["staff"],
    }


def casdoor_user(name: str) -> dict | None:
    response = get("/api/accounts", headers=admin_headers())
    response.raise_for_status()
    users = response.json()
    return next((user for user in users if user["name"] == name), None)


def unique_name(prefix: str) -> str:
    return f"e2e-{prefix}-{int(time.time() * 1000)}"


def admin_headers(user_id: str = "account-admin", org_id: str = ORG_ID) -> dict[str, str]:
    return auth_headers(user_id, ["hanhe_admin"], org_id=org_id)


def auth_headers(user_id: str, roles: list[str], org_id: str = ORG_ID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {sign_jwt({'user_id': user_id, 'org_id': org_id, 'role_list': roles}, secret=JWT_SECRET)}",
    }


def audit_log_high_watermark() -> int:
    with sqlite3.connect(AUDIT_DB) as db:
        return db.execute("SELECT COALESCE(MAX(id), 0) FROM audit_logs").fetchone()[0]


def audit_actions_after(log_id: int) -> set[tuple[str, str, str]]:
    response = get(
        f"/api/audit/logs?after_id={log_id}&resource_type=account&limit=100",
        headers=admin_headers("lifecycle-audit-reader"),
    )
    assert response.status_code == 200
    return {
        (row["action_type"], row["resource_id"], row["policy_decision"])
        for row in response.json()["logs"]
    }
