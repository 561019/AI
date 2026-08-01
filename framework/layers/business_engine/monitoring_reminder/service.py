from __future__ import annotations

from typing import Any
from uuid import uuid4

from framework.core import now, standard_response
from framework.envelope import make_internal_envelope
from framework.http import post_json
from framework.layers.business_engine.generic_module_adapter import get_for, post_for
from framework.module_catalog import MODULE_BY_CODE


MODULE = MODULE_BY_CODE["monitoring-reminder"]
MODULE_CODE = MODULE.code


def get(handler: Any) -> bool:
    return get_for(MODULE_CODE, handler)


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != MODULE.interface:
        handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return
    capability = envelope.get("target", {}).get("capability") or envelope.get("action")
    if capability == "monitor.item.register":
        try:
            _register_monitor_item(handler, envelope)
        except RuntimeError as exc:
            handler.send(502, standard_response(envelope, "failed", error={
                "code": "MONITOR_ITEM_PERSISTENCE_FAILED",
                "message": str(exc),
            }))
        return
    post_for(MODULE_CODE, handler, envelope)


def _register_monitor_item(handler: Any, envelope: dict[str, Any]) -> None:
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    actor = envelope.get("actor") or {}
    context = envelope.get("context") if isinstance(envelope.get("context"), dict) else {}
    monitor_context = payload.get("monitor_context")
    input_data_refs = payload.get("input_data_refs") if isinstance(payload.get("input_data_refs"), list) else []
    monitor_items = _monitor_items_from_payload(payload)

    records = []
    for index, item in enumerate(monitor_items, start=1):
        monitor_item_id = str(item.get("monitor_item_id") or f"monitor-{payload.get('platform_task_id') or uuid4()}-{index}")
        records.append({
            "monitor_item_id": monitor_item_id,
            "record_id": monitor_item_id,
            "tenant_id": actor.get("tenant_id") or "web-workbench",
            "owner_account_id": actor.get("user_id") or actor.get("actor_id") or payload.get("owner_account_id"),
            "project_id": payload.get("project_id") or context.get("project_id"),
            "conversation_id": payload.get("conversation_id") or context.get("conversation_id"),
            "workflow_task_id": payload.get("platform_task_id"),
            "title": item.get("title") or "后续执行监控事项",
            "state": item.get("state") or "registered",
            "monitor_context": monitor_context,
            "input_data_refs": input_data_refs,
            "trigger_conditions": item.get("trigger_conditions") or _default_trigger_conditions(payload),
            "reminder_policy": item.get("reminder_policy") or {"mode": "manual_review", "recipient": "current_user"},
            "created_at": now(),
            "updated_at": now(),
        })

    storage = _data_call(envelope, "foundation_data.write", {
        "dataset": "monitor_items",
        "operation": "upsert",
        "records": records,
    })
    handler.send(200, standard_response(envelope, "success", data={
        "state": "registered",
        "module": MODULE_CODE,
        "module_name_cn": MODULE.name_cn,
        "platform_capability": "monitor.item.register",
        "monitor_items": records,
        "storage": storage,
    }))


def _monitor_items_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("monitor_items")
    if isinstance(items, list) and all(isinstance(item, dict) for item in items):
        return items
    context = payload.get("monitor_context")
    text = str(context or payload.get("user_goal") or "")
    result = []
    if any(token in text for token in ("执行", "落地", "监控", "提醒", "预警")):
        result.append({"title": "后续执行进度监控", "state": "registered"})
    if any(token in text for token in ("审批", "立项")):
        result.append({"title": "立项审批状态跟踪", "state": "registered"})
    if not result:
        result.append({"title": "流程后续事项监控", "state": "registered"})
    return result


def _default_trigger_conditions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "condition": "人工确认完成后继续推进",
            "source": "workflow_execution",
            "workflow_task_id": payload.get("platform_task_id"),
        }
    ]


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
        context=envelope.get("context") if isinstance(envelope.get("context"), dict) else None,
    )
    status, response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions",
        inner,
        timeout=30,
        caller={"layer": "business_engine", "module": MODULE_CODE},
    )
    if status != 200 or not isinstance(response, dict) or response.get("status") != "success":
        raise RuntimeError(str(response))
    return response.get("data") or {}
