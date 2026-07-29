import base64
import json
import time

from helpers import get, layer_dispatch, post, sign_jwt, x_headers
from l1_support import prepare_identity, prepare_identity_runtime_contract, unique


def test_callback_returns_gateway_jwt_with_identity_claims():
    response = get("/callback?code=e2e-code&state=e2e-state")

    assert response.status_code == 200
    body = response.json()
    token = body["token"]
    claims = _jwt_payload(token)
    assert claims["user_id"] == "casdoor-e2e-user"
    assert claims["org_id"] == "casdoor-e2e-org"
    assert claims["role_list"] == ["admin", "operator"]
    assert claims["exp"] > int(time.time())


def test_valid_gateway_jwt_issues_identity_context_for_l1_permission_flow():
    account_id, position_id = unique("login-account"), unique("login-position")
    prepare_identity(account_id, position_id)
    prepare_identity_runtime_contract(position_id, grant=True)
    response = layer_dispatch(
        account_id=account_id,
        action="identity.context.read_self",
        resource_type="identity_context",
        resource_id=account_id,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_expired_gateway_jwt_is_rejected():
    response = post(
        "/auth/validate",
        headers={
            **x_headers(),
            "X-User-ID": "tool_owner_placeholder",
            "X-Resource-Type": "tool",
            "X-Resource-Owner-ID": "tool_owner_placeholder",
            "X-Action": "create",
            "Authorization": f"Bearer {sign_jwt({**_identity_claims(), 'exp': int(time.time()) - 1}, secret='change-me')}",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"allow": False, "reason": "invalid_token"}


def test_missing_authorization_is_rejected():
    response = post(
        "/auth/validate",
        headers={
            **x_headers(),
            "X-User-ID": "tool_owner_placeholder",
            "X-Resource-Type": "tool",
            "X-Resource-Owner-ID": "tool_owner_placeholder",
            "X-Action": "create",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"allow": False, "reason": "invalid_token"}


def _identity_claims() -> dict[str, object]:
    return {
        "user_id": "casdoor-e2e-user",
        "org_id": "casdoor-e2e-org",
        "role_list": ["admin", "operator"],
    }


def _jwt_payload(token: str) -> dict[str, object]:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode()))
