from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from base64 import urlsafe_b64decode
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .registry import REGISTRY_VERSION, find
from .schemas import LayerRequestEnvelope, LayerResponseEnvelope


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _identity_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _decode_identity_context(token: str | None, secret: str, actor_id: str | None, tenant_id: str) -> dict | None:
    """Verify the short-lived account-gateway IdentityContext HMAC token."""
    if not token or not secret or not actor_id:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    signing_input = f"{parts[0]}.{parts[1]}"
    expected = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    try:
        supplied = urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))
        payload = json.loads(urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not hmac.compare_digest(expected, supplied):
        return None
    if payload.get("user_id") != actor_id or payload.get("tenant_id") != tenant_id or int(payload.get("exp", 0)) <= int(_now().timestamp()):
        return None
    return payload


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Hanhe L1 Layer Interface", version="1.0.0")
    app.state.seen_transfers: set[str] = set()

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "l1_layer_interface", "registry_version": REGISTRY_VERSION}

    @app.post("/api/layer/dispatch", response_model=LayerResponseEnvelope)
    async def dispatch(
        envelope: LayerRequestEnvelope,
        request: Request,
        x_l1_service_id: str | None = Header(default=None),
        x_l1_service_signature: str | None = Header(default=None),
    ):
        completed = _now()
        signed = f"{envelope.request_id}:{envelope.nonce}:{x_l1_service_id or ''}".encode()
        expected = hmac.new(settings.service_secret.encode(), signed, hashlib.sha256).hexdigest() if settings.service_secret else ""
        if not settings.service_secret or x_l1_service_id != envelope.caller_service_id or not x_l1_service_signature or not secrets.compare_digest(x_l1_service_signature, expected):
            return JSONResponse(status_code=403, content=LayerResponseEnvelope(trace_id=envelope.trace_id, request_id=envelope.request_id, transfer_id=envelope.transfer_id, status="deny", error={"code": "UNTRUSTED_L2_CALLER"}, completed_at=completed).model_dump(mode="json"))
        item = find(envelope.target_service_id, envelope.command, envelope.caller_service_id)
        if item is None:
            return JSONResponse(status_code=404, content=LayerResponseEnvelope(trace_id=envelope.trace_id, request_id=envelope.request_id, transfer_id=envelope.transfer_id, status="deny", error={"code": "SERVICE_NOT_REGISTERED"}, completed_at=completed).model_dump(mode="json"))
        if item.required_permission_action != "*" and envelope.action != item.required_permission_action:
            return JSONResponse(status_code=400, content=LayerResponseEnvelope(trace_id=envelope.trace_id, request_id=envelope.request_id, transfer_id=envelope.transfer_id, status="deny", error={"code": "SERVICE_ACTION_MISMATCH"}, completed_at=completed).model_dump(mode="json"))
        if envelope.transfer_id in app.state.seen_transfers:
            return JSONResponse(status_code=409, content=LayerResponseEnvelope(trace_id=envelope.trace_id, request_id=envelope.request_id, transfer_id=envelope.transfer_id, status="deny", error={"code": "TRANSFER_REPLAY"}, completed_at=completed).model_dump(mode="json"))
        app.state.seen_transfers.add(envelope.transfer_id)
        if envelope.executor_type != "system" and not envelope.responsible_actor_id:
            return JSONResponse(status_code=400, content=LayerResponseEnvelope(trace_id=envelope.trace_id, request_id=envelope.request_id, transfer_id=envelope.transfer_id, status="deny", error={"code": "MISSING_RESPONSIBLE_ACTOR"}, completed_at=completed).model_dump(mode="json"))
        verified_context = _decode_identity_context(envelope.identity_context_token, settings.identity_context_secret, envelope.responsible_actor_id, envelope.tenant_id)
        if envelope.executor_type != "system" and verified_context is None:
            return JSONResponse(status_code=403, content=LayerResponseEnvelope(trace_id=envelope.trace_id, request_id=envelope.request_id, transfer_id=envelope.transfer_id, status="deny", error={"code": "INVALID_IDENTITY_CONTEXT"}, completed_at=completed).model_dump(mode="json"))
        permission_payload = {
            "trace_id": envelope.trace_id, "request_id": envelope.request_id,
            "actor_id": envelope.responsible_actor_id or "system", "person_id": envelope.responsible_actor_id,
            "action": envelope.action, "source_service": "l1_internal_channel", "target_service": envelope.target_service_id,
            "data_label": envelope.data_label, "data_state": envelope.data_state, "tenant_id": envelope.tenant_id,
            "resource_type": envelope.resource_type, "resource_id": envelope.resource_id,
            "domain_id": str(envelope.payload.get("domain_id") or "") or None,
            "responsible_actor_id": envelope.responsible_actor_id, "executor_type": envelope.executor_type,
            "executor_id": envelope.executor_id, "ingress_mode": "mechanism_direct",
            "original_caller_service_id": envelope.caller_service_id, "transfer_id": envelope.transfer_id,
            "service_registry_version": REGISTRY_VERSION, "identity_context_hash": _identity_hash(verified_context or envelope.identity_context),
            "identity_position_ids": (verified_context or {}).get("position_ids", []),
            "identity_managed_person_ids": (verified_context or {}).get("managed_person_ids", []),
        }
        try:
            async with httpx.AsyncClient(timeout=settings.timeout_ms / 1000) as client:
                permission = await client.post(settings.permission_url + "/api/permission/check", json=permission_payload, headers={"X-L1-Caller-Service": "l1_internal_channel", "X-L1-Mechanism-Secret": settings.permission_mechanism_secret})
            decision = permission.json()
        except (httpx.HTTPError, ValueError):
            return JSONResponse(status_code=503, content=LayerResponseEnvelope(trace_id=envelope.trace_id, request_id=envelope.request_id, transfer_id=envelope.transfer_id, status="error", error={"code": "PERMISSION_UNAVAILABLE"}, completed_at=_now()).model_dump(mode="json"))
        if permission.status_code != 200:
            status_code = 400 if permission.status_code in {400, 422} else 503
            return JSONResponse(status_code=status_code, content=LayerResponseEnvelope(trace_id=envelope.trace_id, request_id=envelope.request_id, transfer_id=envelope.transfer_id, status="error", error={"code": decision.get("reason_code", "PERMISSION_UNAVAILABLE")}, permission_decision_id=decision.get("decision_id"), completed_at=_now()).model_dump(mode="json"))
        if not decision.get("allowed") or decision.get("result") != "allow":
            return JSONResponse(status_code=403, content=LayerResponseEnvelope(trace_id=envelope.trace_id, request_id=envelope.request_id, transfer_id=envelope.transfer_id, status="deny", error={"code": decision.get("reason_code", "PERMISSION_DENIED")}, permission_decision_id=decision.get("decision_id"), completed_at=_now()).model_dump(mode="json"))
        if not item.target_url or not settings.target_service_secret:
            return JSONResponse(status_code=503, content=LayerResponseEnvelope(trace_id=envelope.trace_id, request_id=envelope.request_id, transfer_id=envelope.transfer_id, status="error", error={"code": "TARGET_HANDLER_NOT_ADOPTED", "service_id": item.service_id}, permission_decision_id=decision["decision_id"], completed_at=_now()).model_dump(mode="json"))
        try:
            async with httpx.AsyncClient(timeout=settings.timeout_ms / 1000) as client:
                target_url = item.target_url.replace("http://127.0.0.1:8080", settings.account_gateway_url, 1)
                target = await client.post(target_url, json=envelope.model_dump(mode="json"), headers={"X-L1-Caller-Service": "l1_layer_interface", "X-L1-Target-Secret": settings.target_service_secret, "X-L1-Permission-Decision-ID": decision["decision_id"]})
            target_body = target.json()
        except (httpx.HTTPError, ValueError):
            return JSONResponse(status_code=503, content=LayerResponseEnvelope(trace_id=envelope.trace_id, request_id=envelope.request_id, transfer_id=envelope.transfer_id, status="error", error={"code": "TARGET_UNAVAILABLE", "service_id": item.service_id}, permission_decision_id=decision["decision_id"], completed_at=_now()).model_dump(mode="json"))
        if target.status_code < 200 or target.status_code >= 300:
            return JSONResponse(status_code=502, content=LayerResponseEnvelope(trace_id=envelope.trace_id, request_id=envelope.request_id, transfer_id=envelope.transfer_id, status="error", error={"code": "TARGET_REJECTED", "service_id": item.service_id, "target_status": target.status_code}, permission_decision_id=decision["decision_id"], completed_at=_now()).model_dump(mode="json"))
        return LayerResponseEnvelope(trace_id=envelope.trace_id, request_id=envelope.request_id, transfer_id=envelope.transfer_id, status="success", result=target_body, permission_decision_id=decision["decision_id"], completed_at=_now())

    return app


app = create_app()
