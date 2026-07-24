from __future__ import annotations

from typing import Any
from uuid import uuid4

from framework.core import standard_response
from framework.envelope import make_internal_envelope
from framework.http import post_json
from framework.module_catalog import MODULE_BY_CODE


MODULE = MODULE_BY_CODE["human-collaboration"]


def get(handler: Any) -> bool:
    if handler.path == "/api/v1/capabilities":
        handler.send(200, {"items": [{"capability_code": item, "enabled": True} for item in MODULE.capabilities]})
        return True
    return False


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != MODULE.interface:
        handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return
    capability = envelope.get("target", {}).get("capability") or envelope.get("action")
    if capability not in MODULE.capabilities:
        handler.send(422, standard_response(envelope, "failed", error={"code": "CAPABILITY_NOT_SUPPORTED", "capability": capability}))
        return
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    if capability == "human.task.create":
        _create(handler, envelope, payload)
        return
    if capability == "human.task.query":
        _query(handler, envelope, payload)
        return
    handler.send(422, standard_response(envelope, "failed", error={
        "code": "HUMAN_TASK_ACTION_NOT_IMPLEMENTED", "capability": capability,
        "message": "only task creation and query are enabled in the local collaboration module",
    }))


def _create(handler: Any, envelope: dict[str, Any], payload: dict[str, Any]) -> None:
    actor = envelope.get("actor") or {}
    context = envelope.get("context") or {}
    task_id = str(payload.get("human_task_id") or f"human-{payload.get('platform_task_id') or envelope.get('request_id')}")
    assignee = str(payload.get("assignee") or payload.get("assignee_id") or actor.get("user_id") or actor.get("actor_id") or "")
    if not assignee:
        handler.send(422, standard_response(envelope, "failed", error={"code": "HUMAN_TASK_ASSIGNEE_REQUIRED"}))
        return
    record = {
        "human_task_id": task_id, "record_id": task_id, "assignee_id": assignee,
        "task_type": payload.get("task_type") or "human_confirmation", "state": "pending",
        "cards": payload.get("cards") if isinstance(payload.get("cards"), list) else [],
        "tenant_id": actor.get("tenant_id"), "owner_account_id": actor.get("user_id") or actor.get("actor_id"),
        "project_id": context.get("project_id"), "conversation_id": context.get("conversation_id"),
        "workflow_task_id": payload.get("platform_task_id"),
    }
    status, response = _foundation_data(envelope, "foundation_data.write", {"dataset": "human_tasks", "operation": "upsert", "records": [record]})
    if status != 200 or not isinstance(response, dict) or response.get("status") != "success":
        handler.send(502, standard_response(envelope, "failed", error={"code": "HUMAN_TASK_PERSISTENCE_FAILED", "details": response}))
        return
    handler.send(200, standard_response(envelope, "success", data={
        "state": "created", "module": MODULE.code, "platform_capability": "human.task.create",
        "human_task_id": task_id, "assignee_id": assignee,
        "pending_items": [
            str(card.get("title")) for card in record["cards"]
            if isinstance(card, dict) and card.get("title")
        ],
        "storage": {"dataset": "human_tasks", "writer": "foundation-data"},
    }))


def _query(handler: Any, envelope: dict[str, Any], payload: dict[str, Any]) -> None:
    status, response = _foundation_data(envelope, "foundation_data.query", {
        "dataset": "human_tasks", "filters": payload.get("filters") or {}, "limit": payload.get("limit", 100),
    })
    if status != 200 or not isinstance(response, dict) or response.get("status") != "success":
        handler.send(502, standard_response(envelope, "failed", error={"code": "HUMAN_TASK_QUERY_FAILED", "details": response}))
        return
    handler.send(200, standard_response(envelope, "success", data=response.get("data")))


def _foundation_data(envelope: dict[str, Any], capability: str, payload: dict[str, Any]) -> tuple[int, Any]:
    task_id = str((envelope.get("payload") or {}).get("platform_task_id") or envelope.get("request_id") or uuid4())
    inner = make_internal_envelope(
        str(envelope.get("trace_id")), envelope.get("actor") or {}, task_id,
        capability, "foundation", "foundation-gateway", payload,
        source_layer="foundation", source_module=MODULE.code,
        context=envelope.get("context") if isinstance(envelope.get("context"), dict) else None,
    )
    return post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions", inner, timeout=30,
        caller={"layer": "foundation", "module": MODULE.code},
    )
