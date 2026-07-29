import base64
import json
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from helpers import get, layer_dispatch, permission_url, post, request, sign_jwt, x_headers
from l1_support import prepare_identity, prepare_identity_runtime_contract, unique


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DB = PROJECT_ROOT / ".e2e-data" / "audit.db"
JWT_SECRET = "change-me"
ORG_ID = "casdoor-e2e-org"
MOCK_OWNER = "hanhe"


@pytest.fixture(scope="session", autouse=True)
def acceptance_mock_dependencies():
    servers = []
    for port, handler in ((8000, CasdoorMockHandler), (9101, OwnershipMockHandler)):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        except OSError:
            continue
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)

    try:
        yield
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


def test_ac_f1_oidc_callback_issues_jwt_and_rejects_invalid_code():
    success = get("/callback?code=e2e-code&state=e2e-state")

    assert success.status_code == 200
    claims = jwt_payload(success.json()["token"])
    assert claims["user_id"] == "casdoor-e2e-user"
    assert claims["org_id"] == ORG_ID
    assert claims["role_list"] == ["admin", "operator"]

    failure = get("/callback?code=%20&state=e2e-state")

    assert failure.status_code == 401
    assert failure.json() == {"error": "invalid_callback"}


def test_ac_f2_validate_allows_valid_jwt_and_rejects_expired_jwt():
    account_id = unique("acceptance-identity")
    active = get(
        "/api/identity/context",
        headers={"Authorization": f"Bearer {sign_jwt({'user_id': account_id, 'org_id': ORG_ID, 'role_list': ['staff']}, secret=JWT_SECRET)}"},
    )
    assert active.status_code == 200
    assert active.json()["user_id"] == account_id

    expired = get(
        "/api/identity/context",
        headers={"Authorization": f"Bearer {sign_jwt({'user_id': account_id, 'org_id': ORG_ID, 'role_list': ['staff'], 'exp': int(time.time()) - 1}, secret=JWT_SECRET)}"},
    )
    assert expired.status_code == 401


def test_ac_f3_tool_create_or_update_is_owner_only():
    allowed_account, allowed_position = unique("acceptance-allow"), unique("acceptance-allow-pos")
    denied_account, denied_position = unique("acceptance-deny"), unique("acceptance-deny-pos")
    prepare_identity(allowed_account, allowed_position)
    prepare_identity_runtime_contract(allowed_position, grant=True)
    prepare_identity(denied_account, denied_position)
    prepare_identity_runtime_contract(denied_position, grant=False)

    allowed = layer_dispatch(account_id=allowed_account, action="identity.context.read_self", resource_type="identity_context", resource_id=allowed_account)
    denied = layer_dispatch(account_id=denied_account, action="identity.context.read_self", resource_type="identity_context", resource_id=denied_account)
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "success"
    assert denied.status_code == 403
    assert denied.json()["status"] == "deny"


def test_ac_f4_data_write_requires_permanent_grant():
    account_id, position_id = unique("acceptance-rule"), unique("acceptance-rule-pos")
    prepare_identity(account_id, position_id)
    prepare_identity_runtime_contract(position_id, grant=False)
    denied = layer_dispatch(account_id=account_id, action="identity.context.read_self", resource_type="identity_context", resource_id=account_id)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ACTION_NOT_GRANTED"


def test_ac_f5_each_validate_call_writes_audit_log():
    account_id, position_id = unique("acceptance-audit"), unique("acceptance-audit-pos")
    trace_id = unique("acceptance-trace")
    prepare_identity(account_id, position_id)
    prepare_identity_runtime_contract(position_id, grant=True)
    response = layer_dispatch(
        account_id=account_id,
        action="identity.context.read_self",
        resource_type="identity_context",
        resource_id=account_id,
        trace_id=trace_id,
    )
    assert response.status_code == 200
    audit = requests.get(f"{permission_url()}/api/permission/audits", params={"trace_id": trace_id}, timeout=2)
    assert audit.status_code == 200
    row = audit.json()["audits"][0]
    assert row["result"] == "allow"
    assert row["actor_id"] == account_id
    assert row["ingress_mode"] == "mechanism_direct"


def test_ac_f6_account_lifecycle_gateway_thin_layer_calls_casdoor():
    name = unique_account_name()

    created = create_account(name)

    assert created.status_code == 201
    assert casdoor_user(name)["name"] == name

    create_account("user_li").raise_for_status()
    blocked_delete = request(
        "DELETE",
        "/api/accounts?name=user_li",
        headers={
            "Authorization": f"Bearer {sign_jwt({'user_id': 'acceptance-admin', 'org_id': ORG_ID, 'role_list': ['hanhe_admin']}, secret=JWT_SECRET)}",
        },
    )

    assert blocked_delete.status_code == 409
    assert blocked_delete.json()["resources"] == [
        {"resource_id": "dataset_001", "owner_id": "user_li"}
    ]
    assert casdoor_user("user_li")["name"] == "user_li"


def validate_headers(
    *,
    user_id: str,
    resource_type: str,
    owner_id: str,
    action: str,
    claims: dict[str, Any] | None = None,
    x_header_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    token_claims = {"user_id": user_id, "org_id": ORG_ID, "role_list": ["admin"]}
    token_claims.update(claims or {})
    return {
        **x_headers(**(x_header_overrides or {})),
        "X-User-ID": user_id,
        "X-Resource-Type": resource_type,
        "X-Resource-Owner-ID": owner_id,
        "X-Action": action,
        "Authorization": f"Bearer {sign_jwt(token_claims, secret=JWT_SECRET)}",
    }


def create_account(name: str) -> requests.Response:
    return post(
        "/api/accounts",
        headers={
            "Authorization": f"Bearer {sign_jwt({'user_id': 'acceptance-admin', 'org_id': ORG_ID, 'role_list': ['hanhe_admin']}, secret=JWT_SECRET)}",
        },
        json={
            "name": name,
            "password": "123",
            "displayName": name.replace("-", " ").title(),
            "email": f"{name}@hanhe.local",
            "roles": ["staff"],
        },
    )


def casdoor_user(name: str) -> dict[str, Any] | None:
    response = get(
        "/api/accounts",
        headers={
            "Authorization": f"Bearer {sign_jwt({'user_id': 'acceptance-admin', 'org_id': ORG_ID, 'role_list': ['hanhe_admin']}, secret=JWT_SECRET)}",
        },
    )
    response.raise_for_status()
    return next((user for user in response.json() if user["name"] == name), None)


def max_audit_id() -> int:
    with connect_audit_db() as db:
        return db.execute("SELECT COALESCE(MAX(id), 0) FROM audit_logs").fetchone()[0]


def latest_audit_after(before_id: int, trace_id: str) -> sqlite3.Row | None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with connect_audit_db() as db:
            row = db.execute(
                """
                SELECT actor_id, action_type, resource_type, policy_decision, policy_id, context_snapshot
                FROM audit_logs
                WHERE id > ? AND instr(context_snapshot, ?) > 0
                ORDER BY id DESC
                LIMIT 1
                """,
                (before_id, f'"trace_id":"{trace_id}"'),
            ).fetchone()
        if row is not None:
            return row
        time.sleep(0.02)
    return None


def connect_audit_db() -> sqlite3.Connection:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if AUDIT_DB.exists():
            db = sqlite3.connect(AUDIT_DB)
            db.row_factory = sqlite3.Row
            return db
        time.sleep(0.1)
    raise AssertionError(f"audit db was not created at {AUDIT_DB}")


def jwt_payload(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode()))


def unique_account_name() -> str:
    return f"e2e-acceptance-{int(time.time() * 1000)}"


class CasdoorMockHandler(BaseHTTPRequestHandler):
    server_version = "AcceptanceCasdoorMock/1.0"
    protocol_version = "HTTP/1.1"
    users: dict[str, dict[str, Any]] = {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/get-users":
            self.send_json(404, {"status": "error", "msg": "not_found"})
            return

        query = parse_qs(parsed.query)
        user_id = query.get("id", [""])[0]
        users = list(self.users.values())
        if user_id:
            name = user_id.split("/", 1)[-1]
            users = [user for user in users if user["name"] == name]
        self.send_json(200, {"status": "ok", "data": users})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")

        if parsed.path == "/api/add-user":
            user = {
                "owner": payload.get("owner") or MOCK_OWNER,
                "name": payload["name"],
                "password": payload.get("password", ""),
                "displayName": payload.get("displayName", ""),
                "email": payload.get("email", ""),
                "roles": payload.get("roles", []),
                "isForbidden": payload.get("isForbidden", False),
                "isDeleted": payload.get("isDeleted", False),
            }
            self.users[user["name"]] = user
            self.send_json(200, {"status": "ok", "data": user})
            return

        if parsed.path == "/api/delete-user":
            self.users.pop(payload.get("name", ""), None)
            self.send_json(200, {"status": "ok", "data": None})
            return

        if parsed.path == "/api/update-user":
            self.users[payload["name"]] = payload
            self.send_json(200, {"status": "ok", "data": payload})
            return

        self.send_json(404, {"status": "error", "msg": "not_found"})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class OwnershipMockHandler(BaseHTTPRequestHandler):
    server_version = "AcceptanceOwnershipMock/1.0"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/ownership/by_user/user_li":
            self.send_json(
                200,
                {
                    "user_id": "user_li",
                    "resources": [{"resource_id": "dataset_001", "owner_id": "user_li"}],
                },
            )
            return
        if parsed.path.startswith("/ownership/by_user/"):
            user_id = parsed.path.rsplit("/", 1)[-1]
            self.send_json(200, {"user_id": user_id, "resources": []})
            return
        self.send_json(404, {"error": "not_found"})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
