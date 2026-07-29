from __future__ import annotations

import hashlib
import hmac
import base64
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _payload() -> dict:
    return {
        "trace_id": "trace-1", "request_id": "request-1", "transfer_id": "transfer-1",
        "caller_layer": "L2", "caller_service_id": "content_generation",
        "target_service_id": "account.identity_context.v1", "command": "identity.context.read_self",
        "tenant_id": "tenant-1", "responsible_actor_id": "user-1", "executor_type": "human",
        "executor_id": "user-1", "resource_type": "identity_context", "resource_id": "user-1",
        "action": "identity.context.read_self", "data_label": "normal", "data_state": "active",
        "requested_at": datetime.now(timezone.utc).isoformat(), "nonce": "nonce-1",
    }


def _headers(payload: dict) -> dict[str, str]:
    service = payload["caller_service_id"]
    source = f"{payload['request_id']}:{payload['nonce']}:{service}".encode()
    return {"X-L1-Service-ID": service, "X-L1-Service-Signature": hmac.new(b"test-service-secret", source, hashlib.sha256).hexdigest()}


def _identity_token(payload: dict) -> str:
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=").decode()
    header = encode({"alg": "HS256", "typ": "IdentityContext"})
    body = encode({"user_id": payload["responsible_actor_id"], "tenant_id": payload["tenant_id"], "exp": int(datetime.now(timezone.utc).timestamp()) + 60})
    signed = f"{header}.{body}"
    signature = base64.urlsafe_b64encode(hmac.new(b"test-context-secret", signed.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{signed}.{signature}"


def test_only_signed_l2_request_enters_channel():
    app = create_app(Settings(service_secret="test-service-secret", permission_mechanism_secret="test-permission-secret"))
    with TestClient(app) as client:
        response = client.post("/api/layer/dispatch", json=_payload())
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "UNTRUSTED_L2_CALLER"


def test_unregistered_target_is_denied_before_permission_call():
    app = create_app(Settings(service_secret="test-service-secret", permission_mechanism_secret="test-permission-secret"))
    payload = _payload()
    payload["target_service_id"] = "unregistered.service.v1"
    with TestClient(app) as client:
        response = client.post("/api/layer/dispatch", json=payload, headers=_headers(payload))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SERVICE_NOT_REGISTERED"


def test_registered_request_requires_gateway_identity_context():
    app = create_app(Settings(service_secret="test-service-secret", identity_context_secret="test-context-secret", permission_mechanism_secret="test-permission-secret"))
    payload = _payload()
    with TestClient(app) as client:
        response = client.post("/api/layer/dispatch", json=payload, headers=_headers(payload))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INVALID_IDENTITY_CONTEXT"
