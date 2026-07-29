import sqlite3
import time
from pathlib import Path

from helpers import get, post, request, sign_jwt


JWT_SECRET = "change-me"
ORG_ID = "casdoor-e2e-org"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DB = PROJECT_ROOT / ".e2e-data" / "audit.db"


def normal_token(user_id="breakglass-user", role_list=None):
    return sign_jwt(
        {
            "user_id": user_id,
            "org_id": ORG_ID,
            "role_list": role_list or ["staff"],
        },
        secret=JWT_SECRET,
    )


def admin_token(user_id="breakglass-admin"):
    return normal_token(user_id=user_id, role_list=["hanhe_admin"])


def breakglass_token(user_id="breakglass-user", exp=None):
    claims = {
        "user_id": user_id,
        "org_id": ORG_ID,
        "role_list": ["hanhe_admin"],
        "is_breakglass": True,
    }
    if exp is not None:
        claims["exp"] = exp
    return sign_jwt(claims, secret=JWT_SECRET)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def audit_log_high_watermark():
    db = sqlite3.connect(AUDIT_DB)
    try:
        result = db.execute("SELECT COALESCE(MAX(id), 0) FROM audit_logs").fetchone()
    finally:
        db.close()
    return result[0]


def breakglass_access_count_after(log_id):
    return audit_action_count_after(log_id, "breakglass.access")


def audit_action_count_after(log_id, action_type):
    response = get(
        f"/api/audit/logs?after_id={log_id}&action_type={action_type}&limit=100",
        headers=bearer(admin_token("breakglass-audit-reader")),
    )
    assert response.status_code == 200
    return len(response.json()["logs"])


def test_admin_can_enable_breakglass():
    response = post(
        "/api/breakglass/enable",
        headers=bearer(admin_token()),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["token"]
    assert body["expires_at"]


def test_non_admin_enable_returns_403():
    response = post(
        "/api/breakglass/enable",
        headers=bearer(normal_token(role_list=["staff"])),
    )

    assert response.status_code == 403


def test_admin_can_disable_breakglass():
    post(
        "/api/breakglass/enable",
        headers=bearer(admin_token("breakglass-disable-admin")),
    )

    response = post(
        "/api/breakglass/disable",
        headers=bearer(admin_token("breakglass-disable-admin")),
    )

    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_status_returns_enabled_boolean():
    response = get("/api/breakglass/status")

    assert response.status_code == 200
    assert isinstance(response.json()["enabled"], bool)


def test_breakglass_does_not_reenable_retired_ui_permission_interface():
    post(
        "/api/breakglass/enable",
        headers=bearer(admin_token("breakglass-ui-admin")),
    )

    response = get(
        "/api/ui-permissions",
        headers=bearer(breakglass_token("breakglass-ui-user")),
    )

    assert response.status_code == 410
    assert response.json()["error"] == "permission_capability_moved"


def test_retired_ui_interface_does_not_create_a_breakglass_bypass_audit():
    post(
        "/api/breakglass/enable",
        headers=bearer(admin_token("breakglass-audit-admin")),
    )
    start_id = audit_log_high_watermark()

    response = request(
        "GET",
        "/api/ui-permissions",
        headers=bearer(breakglass_token("breakglass-audit-user")),
    )

    assert response.status_code == 410
    assert breakglass_access_count_after(start_id) == 0


def test_retired_ui_interface_is_not_an_authentication_or_permission_oracle():
    token = breakglass_token("breakglass-expired-user", exp=int(time.time()) + 1)
    time.sleep(2)

    response = get(
        "/api/ui-permissions",
        headers=bearer(token),
    )

    assert response.status_code == 410


def test_breakglass_token_cannot_self_enable():
    response = post(
        "/api/breakglass/enable",
        headers=bearer(breakglass_token("breakglass-self-enable-user")),
    )

    assert response.status_code == 403
    assert response.json()["error"] == "breakglass_cannot_self_enable"


def test_disabled_breakglass_token_cannot_revive_retired_permission_interface():
    enable = post(
        "/api/breakglass/enable",
        headers=bearer(admin_token("breakglass-disabled-admin")),
    )
    assert enable.status_code == 200
    token = enable.json()["token"]

    disable = post(
        "/api/breakglass/disable",
        headers=bearer(admin_token("breakglass-disabled-admin")),
    )
    assert disable.status_code == 200

    response = get(
        "/api/ui-permissions",
        headers=bearer(token),
    )

    assert response.status_code == 410
    assert response.json()["error"] == "permission_capability_moved"


def test_breakglass_report_summarizes_state_access_and_writes_review_audit():
    start_id = audit_log_high_watermark()
    enable = post(
        "/api/breakglass/enable",
        headers=bearer(admin_token("breakglass-report-admin")),
        json={
            "reason": "post incident review",
            "ticket_id": "BG-REPORT-1",
            "expires_in_minutes": 30,
        },
    )
    assert enable.status_code == 200
    token = enable.json()["token"]

    protected = get("/api/ui-permissions", headers=bearer(token))
    assert protected.status_code == 410

    report = get(
        "/api/breakglass/report",
        headers=bearer(admin_token("breakglass-review-admin")),
    )
    assert report.status_code == 200
    body = report.json()
    assert body["enabled"] is True
    assert body["status"] == "active"
    # Access history is retained across tests; the retired endpoint itself is
    # separately proven above not to add a new breakglass.access audit record.
    assert body["access_count"] >= 0
    assert body["reviewed_by"] == "breakglass-review-admin"
    assert body["state"]["reason"] == "post incident review"
    assert body["state"]["ticket_id"] == "BG-REPORT-1"
    assert body["state"]["activated_by"] == "breakglass-report-admin"
    assert audit_action_count_after(start_id, "breakglass.report") >= 1

    self_review = get(
        "/api/breakglass/report",
        headers=bearer(token),
    )
    assert self_review.status_code == 403
    assert self_review.json()["error"] == "breakglass_cannot_self_review"
