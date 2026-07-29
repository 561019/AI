import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

import requests


DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_PERMISSION_URL = "http://127.0.0.1:8001"
DEFAULT_LAYER_URL = "http://127.0.0.1:8002"
E2E_TENANT_ID = "casdoor-e2e-org"
E2E_L2_SERVICE_ID = "e2e_business_engine"


def base_url() -> str:
    return os.environ.get("ACCOUNT_GATEWAY_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def permission_url() -> str:
    return os.environ.get("PERMISSION_GATEWAY_BASE_URL", DEFAULT_PERMISSION_URL).rstrip("/")


def layer_url() -> str:
    return os.environ.get("L1_LAYER_INTERFACE_BASE_URL", DEFAULT_LAYER_URL).rstrip("/")


def request(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    **kwargs: Any,
) -> requests.Response:
    request_timeout = timeout or float(os.environ.get("E2E_REQUEST_TIMEOUT", "2"))
    return requests.request(
        method,
        f"{base_url()}{_normalize_path(path)}",
        headers={**x_headers(), **(headers or {})},
        timeout=request_timeout,
        **kwargs,
    )


def get(path: str, **kwargs: Any) -> requests.Response:
    return request("GET", path, **kwargs)


def post(path: str, **kwargs: Any) -> requests.Response:
    return request("POST", path, **kwargs)


def permission_command(
    action: str, payload: dict[str, Any], *, organization: bool = False, tenant_id: str = E2E_TENANT_ID
) -> requests.Response:
    path = "/api/org/commands" if organization else "/api/permissions/commands"
    headers = {
        "X-Actor-ID": "e2e-permission-admin",
        "X-Actor-Roles": "hanhe_admin,hanhe_im,hanhe_dsm",
        "X-Tenant-ID": tenant_id,
    }
    return requests.post(
        f"{permission_url()}{path}",
        headers=headers,
        json={"action": action, "payload": {"tenant_id": tenant_id, **payload}},
        timeout=float(os.environ.get("E2E_REQUEST_TIMEOUT", "2")),
    )


def identity_context(account_id: str, *, roles: list[str] | None = None, tenant_id: str = E2E_TENANT_ID) -> dict[str, Any]:
    response = get(
        "/api/identity/context",
        headers=auth_headers(
            {"user_id": account_id, "org_id": tenant_id, "role_list": roles or ["staff"]},
            **{},
        ),
    )
    response.raise_for_status()
    return response.json()


def layer_dispatch(
    *,
    account_id: str,
    action: str,
    resource_type: str,
    resource_id: str | None,
    target_service_id: str = "account.identity_context.v1",
    command: str = "identity.context.read_self",
    data_label: str = "normal",
    data_state: str = "active",
    trace_id: str | None = None,
    request_id: str | None = None,
    transfer_id: str | None = None,
    executor_type: str = "human",
    executor_id: str | None = None,
    domain_id: str | None = None,
    tenant_id: str = E2E_TENANT_ID,
) -> requests.Response:
    now = int(time.time() * 1000)
    request_id = request_id or f"request-e2e-{now}"
    transfer_id = transfer_id or f"transfer-e2e-{now}"
    nonce = f"nonce-e2e-{now}"
    context = identity_context(account_id, tenant_id=tenant_id)
    signing_input = f"{request_id}:{nonce}:{E2E_L2_SERVICE_ID}".encode()
    secret = os.environ.get("L1_INTERFACE_SERVICE_SECRET", "local-dev-l2-service-secret").encode()
    signature = hmac.new(secret, signing_input, hashlib.sha256).hexdigest()
    payload = {
        "contract_version": "v1",
        "trace_id": trace_id or f"trace-e2e-{now}",
        "request_id": request_id,
        "transfer_id": transfer_id,
        "caller_layer": "L2",
        "caller_service_id": E2E_L2_SERVICE_ID,
        "target_service_id": target_service_id,
        "command": command,
        "tenant_id": tenant_id,
        "responsible_actor_id": account_id,
        "executor_type": executor_type,
        "executor_id": executor_id or account_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "action": action,
        "data_label": data_label,
        "data_state": data_state,
        "identity_context_token": context["identity_context_token"],
        "payload": {},
        "requested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "nonce": nonce,
    }
    if domain_id:
        payload["payload"] = {"domain_id": domain_id}
    return requests.post(
        f"{layer_url()}/api/layer/dispatch",
        headers={"X-L1-Service-ID": E2E_L2_SERVICE_ID, "X-L1-Service-Signature": signature},
        json=payload,
        timeout=float(os.environ.get("E2E_REQUEST_TIMEOUT", "2")),
    )


def x_headers(**overrides: str) -> dict[str, str]:
    headers = {
        "X-Request-ID": os.environ.get("E2E_REQUEST_ID", "pytest-e2e"),
        "X-Client-ID": os.environ.get("E2E_CLIENT_ID", "pytest"),
    }
    headers.update(overrides)
    return headers


def auth_headers(claims: dict[str, Any] | None = None, **x_header_overrides: str) -> dict[str, str]:
    return {
        **x_headers(**x_header_overrides),
        "Authorization": f"Bearer {sign_jwt(claims or {})}",
    }


def sign_jwt(claims: dict[str, Any], secret: str | None = None) -> str:
    now = int(time.time())
    payload = {"iat": now, "exp": now + 3600, **claims}
    jwt_secret = (secret or os.environ.get("E2E_JWT_SECRET", "change-me")).encode()
    encoded_header = _b64url_json({"alg": "HS256", "typ": "JWT"})
    encoded_payload = _b64url_json(payload)
    signing_input = f"{encoded_header}.{encoded_payload}".encode()
    signature = hmac.new(jwt_secret, signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{_b64url(signature)}"


def _normalize_path(path: str) -> str:
    return path if path.startswith("/") else f"/{path}"


def _b64url_json(value: dict[str, Any]) -> str:
    return _b64url(json.dumps(value, separators=(",", ":")).encode())


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
