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
        source_id = str(payload.get("knowledge_source_id") or command.get("knowledgeBaseId") or f"ks_{uuid4().hex[:16]}")
        knowledge_base_id = str(payload.get("knowledge_base_id") or command.get("knowledgeBaseId") or source_id)
        uploaded_files = payload.get("uploaded_files") if isinstance(payload.get("uploaded_files"), list) else []
        asset_scope = payload.get("asset_scope") or "personal_knowledge"

        # Reuse a completed index for the same account, knowledge base and file
        # fingerprint. This keeps a repeated upload from reparsing the file.
        reusable = _find_reusable_index(envelope, actor, knowledge_base_id, asset_scope, uploaded_files)
        if reusable:
            existing_source = _find_source(envelope, actor, reusable.get("knowledge_source_id"))
            return {
                "state": "reused",
                "knowledge_source": existing_source or {
                    "knowledge_source_id": reusable.get("knowledge_source_id"),
                    "knowledge_base_id": reusable.get("knowledge_base_id") or knowledge_base_id,
                    "asset_scope": asset_scope,
                    "owner_account_id": actor.get("user_id"),
                },
                "storage": {"state": "reused", "dataset": "knowledge_sources"},
                "asset_storage": {"state": "reused", "asset_id": reusable.get("knowledge_source_id")},
                "knowledge_index_result": {
                    "state": "reused",
                    "reused": True,
                    "knowledge_source_id": reusable.get("knowledge_source_id"),
                    "knowledge_base_id": reusable.get("knowledge_base_id") or knowledge_base_id,
                    "chunk_count": reusable.get("chunk_count", 0),
                    "file_count": len(uploaded_files),
                    "file_summaries": reusable.get("file_summaries") or [],
                },
            }
        record = {
            "knowledge_source_id": source_id,
            "record_id": source_id,
            "tenant_id": actor.get("tenant_id") or "web-workbench",
            "owner_account_id": actor.get("user_id") or command.get("accountId") or "anonymous",
            "project_id": command.get("projectId") or payload.get("project_id"),
            "conversation_id": command.get("conversationId") or payload.get("conversation_id"),
            "knowledge_base_id": knowledge_base_id,
            "knowledge_base_name": command_payload.get("name") or payload.get("knowledge_base_name") or payload.get("name"),
            "asset_scope": asset_scope,
            "source_type": payload.get("source_type") or ("uploaded_file" if uploaded_files else "conversation"),
            "scope": command_payload.get("scope") or payload.get("scope") or "personal",
            "operation": command.get("operation") or capability,
            "request": command_payload.get("request") or payload.get("request"),
            "uploaded_file_ids": [item.get("file_id") for item in uploaded_files if isinstance(item, dict) and item.get("file_id")],
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
            "name": record.get("knowledge_base_name") or source_id,
            "scope": record["scope"],
            "state": "active",
            "source_ref": {"dataset": "knowledge_sources", "record_id": source_id},
            "operation": command.get("operation") or capability,
        })
        index_result = None
        if uploaded_files:
            index_result = _knowledge_base_index_call(envelope, record, uploaded_files)
        return {
            "state": "indexed" if index_result else "registered",
            "knowledge_source": record,
            "storage": storage,
            "asset_storage": asset_storage,
            "knowledge_index_result": index_result,
        }

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
    if status not in {200, 202} or not isinstance(response, dict) or response.get("status") != "success":
        raise RuntimeError(str(response))
    return ((response.get("data") or {}).get("storage_result") or {})


def _knowledge_base_index_call(envelope: dict[str, Any], source_record: dict[str, Any], uploaded_files: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "knowledge_source_id": source_record["knowledge_source_id"],
        "knowledge_base_id": source_record.get("knowledge_base_id") or source_record["knowledge_source_id"],
        "knowledge_base_name": source_record.get("knowledge_base_name"),
        "asset_scope": source_record.get("asset_scope") or "personal_knowledge",
        "knowledge_source": source_record,
        "uploaded_files": uploaded_files,
    }
    inner = make_internal_envelope(
        envelope.get("trace_id"),
        envelope.get("actor") or {"tenant_id": "web-workbench", "user_id": "system", "authenticated": True},
        str((envelope.get("payload") or {}).get("platform_task_id") or envelope.get("request_id") or uuid4()),
        "vector.index.upsert",
        "foundation",
        "foundation-gateway",
        payload,
        source_layer="business_engine",
        source_module=MODULE_CODE,
        context=envelope.get("context") if isinstance(envelope.get("context"), dict) else {},
    )
    status, response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions",
        inner,
        timeout=180,
        caller={"layer": "business_engine", "module": MODULE_CODE},
    )
    if status not in {200, 202} or not isinstance(response, dict) or response.get("status") != "success":
        raise RuntimeError(str(response))
    return response.get("data") or {}


def _find_reusable_index(
    envelope: dict[str, Any],
    actor: dict[str, Any],
    knowledge_base_id: str,
    asset_scope: str,
    uploaded_files: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not uploaded_files:
        return None
    result = _data_call(envelope, "foundation_data.query", {
        "dataset": "knowledge_indexes",
        "filters": {
            "owner_account_id": actor.get("user_id"),
            "knowledge_base_id": knowledge_base_id,
            "asset_scope": asset_scope,
            "state": "indexed",
        },
        "limit": 500,
    })
    indexes = result.get("items") if isinstance(result.get("items"), list) else []
    for index in indexes:
        summaries = index.get("file_summaries") if isinstance(index.get("file_summaries"), list) else []
        if all(_file_matches_summary(item, summaries) for item in uploaded_files if isinstance(item, dict)):
            return index
    return None


def _find_source(envelope: dict[str, Any], actor: dict[str, Any], source_id: Any) -> dict[str, Any] | None:
    if not source_id:
        return None
    result = _data_call(envelope, "foundation_data.query", {
        "dataset": "knowledge_sources",
        "filters": {
            "owner_account_id": actor.get("user_id"),
            "knowledge_source_id": str(source_id),
        },
        "limit": 1,
    })
    items = result.get("items") if isinstance(result.get("items"), list) else []
    return items[0] if items else None


def _file_matches_summary(file_item: dict[str, Any], summaries: list[dict[str, Any]]) -> bool:
    file_id = str(file_item.get("file_id") or file_item.get("object_id") or "")
    sha256 = str(file_item.get("sha256") or "")
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        if sha256 and str(summary.get("sha256") or "") == sha256:
            return True
        if file_id and str(summary.get("file_id") or "") == file_id:
            return True
    return False
