import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from helpers import get, post, request, sign_jwt


JWT_SECRET = "change-me"
ORG_ID = "casdoor-e2e-org"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DB = PROJECT_ROOT / ".e2e-data" / "audit.db"


def cred_token(user_id="cred-test-user", roles=None, org_id=ORG_ID):
    return sign_jwt(
        {"user_id": user_id, "org_id": org_id, "role_list": roles or ["staff"]},
        secret=JWT_SECRET,
    )


def test_store_credential_returns_201():
    response = post(
        "/api/credentials",
        headers={
            "Authorization": f"Bearer {cred_token()}",
            "X-Credential-Value": "sk-secret123",
        },
        json={"name": "openai-key", "type": "api_key"},
    )

    assert response.status_code == 201
    assert response.json()["name"] == "openai-key"


def test_list_credentials_no_raw_value():
    post(
        "/api/credentials",
        headers={
            "Authorization": f"Bearer {cred_token()}",
            "X-Credential-Value": "sk-secret123",
        },
        json={"name": "test-key", "type": "api_key"},
    )

    response = get(
        "/api/credentials",
        headers={"Authorization": f"Bearer {cred_token()}"},
    )

    assert response.status_code == 200
    creds = response.json()["credentials"]
    assert len(creds) > 0
    assert "encrypted_value" not in str(creds[0])
    assert "sk-secret123" not in str(creds)


def test_use_credential_requires_server_side_proxy_and_never_returns_plaintext():
    store = post(
        "/api/credentials",
        headers={
            "Authorization": f"Bearer {cred_token()}",
            "X-Credential-Value": "sk-test-use",
        },
        json={"name": "use-test", "type": "api_key"},
    )
    cred_id = store.json()["id"]

    response = post(
        f"/api/credentials/{cred_id}/use",
        headers={"Authorization": f"Bearer {cred_token()}"},
    )

    assert response.status_code == 501
    assert response.json()["error"] == "credential_proxy_required"
    assert response.headers.get("X-Distributed-Credential") is None
    assert "sk-test-use" not in response.text


def test_unauthorized_use_returns_403():
    store = post(
        "/api/credentials",
        headers={
            "Authorization": f"Bearer {cred_token('user-A')}",
            "X-Credential-Value": "sk-secret",
        },
        json={"name": "auth-test", "type": "api_key"},
    )
    cred_id = store.json()["id"]

    response = post(
        f"/api/credentials/{cred_id}/use",
        headers={
            "Authorization": f"Bearer {cred_token('user-B')}",
            "X-Credential-Value": "x",
        },
    )

    assert response.status_code == 403


def test_encryption_no_plaintext_in_db():
    post(
        "/api/credentials",
        headers={
            "Authorization": f"Bearer {cred_token()}",
            "X-Credential-Value": "sk-plaintest",
        },
        json={"name": "db-test", "type": "api_key"},
    )

    db = sqlite3.connect(AUDIT_DB)
    result = db.execute(
        "SELECT encrypted_value FROM credentials WHERE name='db-test' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    db.close()

    assert result is not None
    assert "sk-plaintest" not in result[0]


def test_admin_can_list_all_credentials():
    post(
        "/api/credentials",
        headers={
            "Authorization": f"Bearer {cred_token('regular-user')}",
            "X-Credential-Value": "sk-admin",
        },
        json={"name": "admin-test", "type": "api_key"},
    )

    response = get(
        "/api/credentials",
        headers={"Authorization": f"Bearer {cred_token('admin-user', ['hanhe_admin'])}"},
    )

    assert response.status_code == 200
    names = [c["name"] for c in response.json()["credentials"]]
    assert "admin-test" in names


def test_credentials_are_isolated_by_tenant_even_for_admin():
    store = post(
        "/api/credentials",
        headers={
            "Authorization": f"Bearer {cred_token('tenant-owner', org_id='tenant-a')}",
            "X-Credential-Value": "sk-tenant-a",
        },
        json={"name": "tenant-a-key", "type": "api_key"},
    )
    assert store.status_code == 201
    cred_id = store.json()["id"]
    assert store.json()["tenant_id"] == "tenant-a"

    tenant_b_list = get(
        "/api/credentials",
        headers={"Authorization": f"Bearer {cred_token('tenant-b-admin', ['hanhe_admin'], org_id='tenant-b')}"},
    )
    assert tenant_b_list.status_code == 200
    assert "tenant-a-key" not in [c["name"] for c in tenant_b_list.json()["credentials"]]

    tenant_b_use = post(
        f"/api/credentials/{cred_id}/use",
        headers={"Authorization": f"Bearer {cred_token('tenant-b-admin', ['hanhe_admin'], org_id='tenant-b')}"},
    )
    assert tenant_b_use.status_code == 404
    assert tenant_b_use.json()["error"] == "credential_not_found"

    tenant_b_delete = request(
        "DELETE",
        f"/api/credentials/{cred_id}",
        headers={"Authorization": f"Bearer {cred_token('tenant-b-admin', ['hanhe_admin'], org_id='tenant-b')}"},
    )
    assert tenant_b_delete.status_code == 404

    tenant_a_admin_use = post(
        f"/api/credentials/{cred_id}/use",
        headers={"Authorization": f"Bearer {cred_token('tenant-a-admin', ['hanhe_admin'], org_id='tenant-a')}"},
    )
    assert tenant_a_admin_use.status_code == 501
    assert tenant_a_admin_use.json()["error"] == "credential_proxy_required"
    assert tenant_a_admin_use.headers.get("X-Distributed-Credential") is None
    assert "sk-tenant-a" not in tenant_a_admin_use.text


def test_delete_credential_removes_it_and_use_returns_404():
    store = post(
        "/api/credentials",
        headers={
            "Authorization": f"Bearer {cred_token('delete-owner')}",
            "X-Credential-Value": "sk-delete",
        },
        json={"name": "delete-test", "type": "api_key"},
    )
    assert store.status_code == 201
    cred_id = store.json()["id"]

    deleted = request(
        "DELETE",
        f"/api/credentials/{cred_id}",
        headers={"Authorization": f"Bearer {cred_token('delete-owner')}"},
    )

    assert deleted.status_code == 204

    use_after_delete = post(
        f"/api/credentials/{cred_id}/use",
        headers={"Authorization": f"Bearer {cred_token('delete-owner')}"},
    )

    assert use_after_delete.status_code == 404
    assert use_after_delete.json()["error"] == "credential_not_found"


def test_expired_credential_cannot_be_used_or_leaked():
    expired_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    store = post(
        "/api/credentials",
        headers={
            "Authorization": f"Bearer {cred_token('expired-owner')}",
            "X-Credential-Value": "sk-expired",
        },
        json={"name": "expired-test", "type": "api_key", "expires_at": expired_at},
    )
    assert store.status_code == 201
    assert store.json()["expires_at"] == expired_at
    assert store.json()["status"] == "expired"
    cred_id = store.json()["id"]

    listing = get(
        "/api/credentials",
        headers={"Authorization": f"Bearer {cred_token('expired-owner')}"},
    )
    assert listing.status_code == 200
    expired = [c for c in listing.json()["credentials"] if c["id"] == cred_id][0]
    assert expired["status"] == "expired"
    assert expired["expires_at"] == expired_at
    assert "sk-expired" not in str(expired)

    use = post(
        f"/api/credentials/{cred_id}/use",
        headers={"Authorization": f"Bearer {cred_token('expired-owner')}"},
    )
    assert use.status_code == 409
    assert use.json()["error"] == "credential_expired"
    assert use.headers.get("X-Distributed-Credential") is None


def test_credential_rejects_invalid_expiry():
    response = post(
        "/api/credentials",
        headers={
            "Authorization": f"Bearer {cred_token('bad-expiry-owner')}",
            "X-Credential-Value": "sk-bad-expiry",
        },
        json={"name": "bad-expiry", "type": "api_key", "expires_at": "tomorrow"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_expires_at"
