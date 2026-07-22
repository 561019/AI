from __future__ import annotations

from typing import Any

from framework.core import standard_response
from framework.envelope import make_internal_envelope
from framework.http import post_json
from framework.module_catalog import MODULE_BY_CODE


MODULE = MODULE_BY_CODE["data-operation"]


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
        handler.send(422, standard_response(envelope, "failed", error={"code": "CAPABILITY_NOT_SUPPORTED_BY_MODULE", "capability": capability}))
        return
    actor = envelope.get("actor") or {}
    if not actor.get("tenant_id"):
        handler.send(422, standard_response(envelope, "failed", error={"code": "TENANT_CONTEXT_REQUIRED"}))
        return
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    foundation_capability, foundation_payload = _translate(capability, payload)
    inner = make_internal_envelope(
        envelope.get("trace_id"),
        actor,
        str(payload.get("platform_task_id") or envelope.get("request_id")),
        foundation_capability,
        "foundation",
        "foundation-gateway",
        foundation_payload,
        source_layer="business_engine",
        source_module="data-operation",
    )
    status, response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions",
        inner,
        caller={"layer": "business_engine", "module": "data-operation"},
    )
    if status != 200 or response.get("status") != "success":
        handler.send(502, standard_response(envelope, "failed", error={"code": "FOUNDATION_DATA_OPERATION_FAILED", "details": response}))
        return
    data = response.get("data") or {}
    if capability == "data.aggregate":
        data = _aggregate(data, payload)
    handler.send(200, standard_response(envelope, "success", data={
        "state": "completed",
        "module": "data-operation",
        "module_name_cn": "数据操作引擎",
        "platform_capability": capability,
        "storage_capability": foundation_capability,
        "storage_result": data,
        "received_payload": payload,
    }))


def _translate(capability: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    dataset = str(payload.get("dataset") or payload.get("collection") or "business_records")
    if capability in {"data.persist", "data.create", "data.update", "data.delete"}:
        operation = {
            "data.persist": payload.get("operation") or "upsert",
            "data.create": "insert",
            "data.update": "update",
            "data.delete": "delete",
        }[capability]
        records = payload.get("records")
        if not isinstance(records, list):
            record = payload.get("record") if isinstance(payload.get("record"), dict) else {
                key: value for key, value in payload.items()
                if key not in {"platform_task_id", "operation", "records", "record"}
            }
            records = [record]
        return "foundation_data.write", {
            "dataset": dataset,
            "operation": operation,
            "records": records,
            **({"writes": payload["writes"]} if isinstance(payload.get("writes"), list) else {}),
        }
    if capability == "data.read" and payload.get("record_id"):
        return "foundation_data.read", {"dataset": dataset, "record_id": payload.get("record_id"), "tenant_id": payload.get("tenant_id")}
    return "foundation_data.query", {
        "dataset": dataset,
        "filters": payload.get("filters") or {},
        "tenant_id": payload.get("tenant_id"),
        "limit": payload.get("limit", 100),
    }


def _aggregate(data: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items") or []
    field = payload.get("aggregate_field")
    if not field:
        return {**data, "aggregate": {"operation": "count", "value": len(items)}}
    values = [item.get(field) for item in items if isinstance(item.get(field), (int, float))]
    return {**data, "aggregate": {"operation": payload.get("aggregate_operation", "sum"), "field": field, "value": sum(values)}}
