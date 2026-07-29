import time

from helpers import get, post, sign_jwt


JWT_SECRET = "change-me"
ORG_ID = "casdoor-e2e-org"


def auth_headers(user_id="placeholder-admin", roles=None, org_id=ORG_ID):
    return {
        "Authorization": f"Bearer {sign_jwt({'user_id': user_id, 'org_id': org_id, 'role_list': roles or ['hanhe_admin']}, secret=JWT_SECRET)}",
    }


def test_legacy_tenant_placeholder_is_real_detail_route():
    tenant_id = f"tenant-detail-e2e-{time.time_ns()}"
    missing = get("/api/tenants/missing-tenant", headers=auth_headers())

    assert missing.status_code == 404
    assert missing.json() == {"error": "tenant_not_found"}

    created = post(
        "/api/tenants",
        headers=auth_headers("tenant-detail-admin"),
        json={"id": tenant_id, "name": "Tenant Detail", "users": ["tenant-detail-user"]},
    )
    assert created.status_code == 201

    detail = get(f"/api/tenants/{tenant_id}", headers=auth_headers("tenant-detail-admin"))
    assert detail.status_code == 200
    assert detail.json()["id"] == tenant_id
    assert detail.json()["users"] == ["tenant-detail-user"]

    cross_tenant = get(
        f"/api/tenants/{tenant_id}",
        headers=auth_headers("other-tenant-user", ["staff"], org_id="other-tenant"),
    )
    assert cross_tenant.status_code == 404
    assert cross_tenant.json() == {"error": "tenant_not_found"}


def test_legacy_integration_placeholder_is_real_provider_route():
    sync = post("/api/integrations/dingtalk/sync", headers=auth_headers("integration-admin"))

    assert sync.status_code == 200
    body = sync.json()
    assert body["provider"] == "dingtalk"
    assert body["mode"] == "mock"
    assert body["status"] == "success"
    assert body["synced"] is True
    assert body["attempted_at"]
    assert body["synced_at"]
    assert body["attempts"] >= 1
    assert body["actor_id"] == "integration-admin"
    assert body["summary"]["departments"] == 3
    assert body["summary"]["positions"] == 4

    status = get("/api/integrations/dingtalk/status", headers=auth_headers("integration-admin"))
    assert status.status_code == 200
    assert status.json()["provider"] == "dingtalk"
    assert status.json()["summary"] == body["summary"]
    assert status.json()["attempts"] == body["attempts"]

    audit_logs = get(
        "/api/audit/logs?action_type=integrations.sync&resource_type=integration&resource_id=dingtalk&limit=20",
        headers=auth_headers("integration-admin"),
    )
    assert audit_logs.status_code == 200
    assert any(
        item["actor_id"] == "integration-admin"
        and item["policy_id"] == "integration_sync:dingtalk:success"
        for item in audit_logs.json()["logs"]
    )

    hr_sync = post("/api/integrations/hr/sync", headers=auth_headers("integration-admin"))
    assert hr_sync.status_code == 200
    assert hr_sync.json()["summary"]["users"] == 3

    unsupported_provider = post("/api/integrations/slack/sync", headers=auth_headers("integration-admin"))
    assert unsupported_provider.status_code == 404
    assert unsupported_provider.json() == {"error": "provider_not_supported"}

    unsupported = get("/api/integrations/dingtalk/example", headers=auth_headers("integration-admin"))
    assert unsupported.status_code == 404
