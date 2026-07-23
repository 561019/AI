from typing import Any
from uuid import uuid4

from framework.core import now, standard_response
from framework.envelope import make_internal_envelope
from framework.http import post_json
from framework.layers.business_engine.generic_module_adapter import get_for, post_for
from framework.module_catalog import MODULE_BY_CODE

MODULE_CODE = "project-management"


def get(handler):
    return get_for(MODULE_CODE, handler)


def post(handler, payload):
    capability = payload.get("target", {}).get("capability") or payload.get("action")
    if capability in {"project.register.simple", "project.register.major"}:
        try:
            _register_project(handler, payload, capability)
        except RuntimeError as exc:
            handler.send(502, standard_response(payload, "failed", error={"code": "PROJECT_PERSISTENCE_FAILED", "message": str(exc)}))
        return
    post_for(MODULE_CODE, handler, payload)


def _register_project(handler: Any, envelope: dict[str, Any], capability: str) -> None:
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    command = payload.get("application_command") if isinstance(payload.get("application_command"), dict) else {}
    command_payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
    project = command_payload.get("project") if isinstance(command_payload.get("project"), dict) else command_payload
    actor = envelope.get("actor") or {}
    project_id = str(project.get("project_id") or project.get("id") or f"project-{uuid4().hex[:12]}")
    name = str(project.get("name") or "未命名 Project").strip()
    record = {
        "project_id": project_id,
        "record_id": project_id,
        "tenant_id": actor.get("tenant_id") or "web-workbench",
        "owner_account_id": actor.get("user_id") or command.get("accountId") or "anonymous",
        "name": name,
        "short": project.get("short") or name[:6],
        "type": project.get("type") or "custom",
        "fixed": False,
        "description": project.get("description") or "由工作台创建的 Project",
        "status": project.get("status") or "已创建",
        "metrics": project.get("metrics") or [],
        "knowledge": project.get("knowledge") or [],
        "created_at": project.get("created_at") or now(),
        "updated_at": now(),
    }
    storage = _data_call(envelope, "foundation_data.write", {
        "dataset": "projects",
        "operation": "upsert",
        "records": [record],
    })
    handler.send(200, standard_response(envelope, "success", data={
        "state": "persisted",
        "project": record,
        "storage": storage,
        "capability": capability,
    }))


def _data_call(envelope: dict[str, Any], capability: str, payload: dict[str, Any]) -> dict[str, Any]:
    inner = make_internal_envelope(
        envelope.get("trace_id") or str(uuid4()),
        envelope.get("actor") or {"tenant_id": "web-workbench", "user_id": "system", "authenticated": True},
        str((envelope.get("payload") or {}).get("platform_task_id") or envelope.get("request_id") or uuid4()),
        capability,
        "foundation",
        "foundation-gateway",
        payload,
        source_layer="business_engine",
        source_module=MODULE_CODE,
    )
    status, response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions",
        inner,
        timeout=30,
        caller={"layer": "business_engine", "module": MODULE_CODE},
    )
    if status != 200 or response.get("status") != "success":
        raise RuntimeError(str(response))
    return response.get("data") or {}
