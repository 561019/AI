from __future__ import annotations

from typing import Any
from uuid import uuid4

from framework.core import now, standard_response
from framework.envelope import make_internal_envelope
from framework.http import post_json
from framework.layers.business_engine.generic_module_adapter import get_for, post_for
from framework.module_catalog import MODULE_BY_CODE

MODULE_CODE = "digital-asset"
MODULE = MODULE_BY_CODE[MODULE_CODE]


def get(handler):
    return get_for(MODULE_CODE, handler)


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != MODULE.interface:
        handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return

    capability = envelope.get("target", {}).get("capability") or envelope.get("action")
    if capability not in MODULE.capabilities:
        handler.send(422, standard_response(envelope, "failed", error={
            "code": "CAPABILITY_NOT_SUPPORTED_BY_MODULE",
            "capability": capability,
            "provider_module": MODULE.code,
        }))
        return

    if capability in {"asset.create", "asset.update", "asset.delete", "asset.query", "knowledge_source.register", "knowledge_source.result.register"}:
        try:
            data = _handle_persistent_asset_command(envelope, capability)
        except RuntimeError as exc:
            handler.send(502, standard_response(envelope, "failed", error={"code": "DIGITAL_ASSET_DATA_OPERATION_FAILED", "message": str(exc)}))
            return
        handler.send(200, standard_response(envelope, "success", data=data))
        return

    post_for(MODULE_CODE, handler, envelope)


def _handle_persistent_asset_command(envelope: dict[str, Any], capability: str) -> dict[str, Any]:
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    command = payload.get("application_command") if isinstance(payload.get("application_command"), dict) else {}
    command_payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
    actor = envelope.get("actor") or {}

    if capability in {"knowledge_source.register", "knowledge_source.result.register"}:
        source_id = str(command.get("knowledgeBaseId") or payload.get("knowledge_source_id") or f"ks_{uuid4().hex[:16]}")
        record = {
            "knowledge_source_id": source_id,
            "record_id": source_id,
            "tenant_id": actor.get("tenant_id") or "web-workbench",
            "owner_account_id": actor.get("user_id") or command.get("accountId") or "anonymous",
            "project_id": command.get("projectId") or payload.get("project_id"),
            "conversation_id": command.get("conversationId") or payload.get("conversation_id"),
            "source_type": "conversation",
            "scope": command_payload.get("scope") or payload.get("scope") or "personal",
            "operation": command.get("operation") or capability,
            "request": command_payload.get("request") or payload.get("request"),
            "source_payload": command_payload or payload,
            "state": "registered",
            "updated_at": now(),
        }
        storage = _data_call(envelope, "foundation_data.write", {
            "dataset": "knowledge_sources",
            "operation": "upsert",
            "records": [record],
        })
        asset_storage = _upsert_asset(envelope, {
            "asset_id": source_id,
            "asset_type": "knowledge_base",
            "name": command_payload.get("name") or payload.get("name") or source_id,
            "scope": record["scope"],
            "state": "active",
            "source_ref": {"dataset": "knowledge_sources", "record_id": source_id},
            "operation": command.get("operation") or capability,
        })
        return {"state": "registered", "knowledge_source": record, "storage": storage, "asset_storage": asset_storage}

    if capability == "asset.query":
        filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
        return _data_call(envelope, "foundation_data.query", {
            "dataset": "digital_assets",
            "filters": filters,
            "limit": payload.get("limit", 100),
        })

    asset_id = str(command.get("capabilityId") or command.get("knowledgeBaseId") or payload.get("asset_id") or f"asset_{uuid4().hex[:16]}")
    asset_type = str(command.get("capabilityType") or payload.get("asset_type") or ("knowledge_base" if command.get("knowledgeBaseId") else "capability"))
    state = "deleted" if capability == "asset.delete" else ("disabled" if command.get("operation") == "deactivate" else "active")
    storage = _upsert_asset(envelope, {
        "asset_id": asset_id,
        "asset_type": asset_type,
        "name": command_payload.get("title") or command_payload.get("name") or payload.get("name") or asset_id,
        "scope": command_payload.get("scope") or payload.get("scope") or "personal",
        "state": state,
        "operation": command.get("operation") or capability,
        "conversation_id": command.get("conversationId") or payload.get("conversation_id"),
        "project_id": command.get("projectId") or payload.get("project_id"),
        "source_payload": command_payload or payload,
    })
    return {"state": state, "asset_id": asset_id, "asset_type": asset_type, "storage": storage}


def _upsert_asset(envelope: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    actor = envelope.get("actor") or {}
    record = {
        "tenant_id": actor.get("tenant_id") or "web-workbench",
        "owner_account_id": actor.get("user_id") or "anonymous",
        "updated_at": now(),
        **values,
        "record_id": values["asset_id"],
    }
    return _data_call(envelope, "foundation_data.write", {
        "dataset": "digital_assets",
        "operation": "upsert",
        "records": [record],
    })


def _data_call(envelope: dict[str, Any], capability: str, payload: dict[str, Any]) -> dict[str, Any]:
    data_capability = {
        "foundation_data.write": "data.persist",
        "foundation_data.read": "data.read",
        "foundation_data.query": "data.search",
    }[capability]
    inner = make_internal_envelope(
        envelope.get("trace_id"),
        envelope.get("actor") or {"tenant_id": "web-workbench", "user_id": "system", "authenticated": True},
        str((envelope.get("payload") or {}).get("platform_task_id") or envelope.get("request_id")),
        data_capability,
        "business_engine",
        "engine-gateway",
        payload,
        source_layer="business_engine",
        source_module=MODULE_CODE,
    )
    status, response = post_json(
        "http://127.0.0.1:8200/api/v1/engine/instructions",
        inner,
        caller={"layer": "business_engine", "module": MODULE_CODE},
    )
    if status != 200 or response.get("status") != "success":
        raise RuntimeError(str(response))
    return ((response.get("data") or {}).get("storage_result") or {})
