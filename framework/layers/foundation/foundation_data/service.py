from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from framework.core import connect, now, standard_response


CAPABILITIES = {
    "foundation_data.read",
    "foundation_data.write",
    "foundation_data.query",
    "foundation_data.source.register",
}
SENSITIVE_DATASETS = {"account_credentials", "account_sessions", "model_secrets", "api_credentials"}


def get(handler: Any) -> bool:
    clean_path = handler.path.split("?", 1)[0]
    if clean_path == "/api/v1/capabilities":
        handler.send(200, {"items": [{"capability_code": item, "enabled": True} for item in sorted(CAPABILITIES)]})
        return True
    if clean_path == "/api/v1/foundation-data/records":
        query = parse_qs(urlparse(handler.path).query)
        dataset = (query.get("dataset") or [""])[0]
        if dataset in SENSITIVE_DATASETS:
            handler.send(403, {"error": {"code": "SENSITIVE_DATASET_FORBIDDEN"}})
            return True
        tenant_id = (query.get("tenant_id") or ["web-workbench"])[0]
        limit = min(max(int((query.get("limit") or ["100"])[0]), 1), 500)
        handler.send(200, {"dataset": dataset, "items": _query_records(dataset, tenant_id, {}, limit)})
        return True
    return False


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != "/api/v1/foundation-data/instructions":
        handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return
    capability = envelope.get("target", {}).get("capability") or envelope.get("action")
    if capability not in CAPABILITIES:
        handler.send(422, standard_response(envelope, "failed", error={"code": "CAPABILITY_NOT_SUPPORTED", "capability": capability}))
        return
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    try:
        if capability == "foundation_data.write":
            data = _write(envelope, payload)
        elif capability == "foundation_data.read":
            data = _read(envelope, payload)
        elif capability == "foundation_data.query":
            data = _query(envelope, payload)
        else:
            data = _register_source(envelope, payload)
    except ValueError as exc:
        handler.send(422, standard_response(envelope, "failed", error={"code": "FOUNDATION_DATA_INPUT_INVALID", "message": str(exc)}))
        return
    handler.send(200, standard_response(envelope, "success", data=data))


def _write(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    writes = payload.get("writes")
    if not isinstance(writes, list):
        writes = [{
            "dataset": payload.get("dataset"),
            "operation": payload.get("operation", "upsert"),
            "records": payload.get("records") if "records" in payload else [payload.get("record")],
        }]
    timestamp = now()
    actor = envelope.get("actor") or {}
    default_tenant = str(actor.get("tenant_id") or "default")
    actor_id = str(actor.get("user_id") or actor.get("actor_id") or "system")
    saved: list[dict[str, Any]] = []
    with connect() as db:
        for write in writes:
            dataset = str(write.get("dataset") or "").strip()
            operation = str(write.get("operation") or "upsert").lower()
            records = write.get("records") or []
            if not dataset:
                raise ValueError("dataset is required")
            if not isinstance(records, list) or not records or any(not isinstance(item, dict) for item in records):
                raise ValueError(f"records are required for dataset {dataset}")
            for source in records:
                record = dict(source)
                record_id = str(record.get("record_id") or _infer_record_id(record) or uuid4())
                tenant_id = str(record.get("tenant_id") or default_tenant)
                record.setdefault("record_id", record_id)
                record.setdefault("tenant_id", tenant_id)
                record.setdefault("trace_id", envelope.get("trace_id"))
                existing = db.execute(
                    "SELECT created_at,payload_json FROM data_records WHERE dataset=? AND tenant_id=? AND record_id=?",
                    (dataset, tenant_id, record_id),
                ).fetchone()
                if operation == "insert" and existing:
                    raise ValueError(f"record already exists: {dataset}/{record_id}")
                if operation == "update" and not existing:
                    raise ValueError(f"record does not exist: {dataset}/{record_id}")
                if operation == "delete":
                    db.execute(
                        "UPDATE data_records SET deleted_at=?,updated_at=?,trace_id=? WHERE dataset=? AND tenant_id=? AND record_id=?",
                        (timestamp, timestamp, envelope.get("trace_id"), dataset, tenant_id, record_id),
                    )
                else:
                    if existing and operation == "update":
                        merged = json.loads(existing["payload_json"])
                        merged.update(record)
                        record = merged
                    created_at = existing["created_at"] if existing else timestamp
                    db.execute(
                        """
                        INSERT INTO data_records(dataset,record_id,tenant_id,owner_account_id,project_id,conversation_id,trace_id,payload_json,created_at,updated_at,deleted_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,NULL)
                        ON CONFLICT(dataset,tenant_id,record_id) DO UPDATE SET
                          tenant_id=excluded.tenant_id,
                          owner_account_id=excluded.owner_account_id,
                          project_id=excluded.project_id,
                          conversation_id=excluded.conversation_id,
                          trace_id=excluded.trace_id,
                          payload_json=excluded.payload_json,
                          updated_at=excluded.updated_at,
                          deleted_at=NULL
                        """,
                        (
                            dataset, record_id, tenant_id,
                            record.get("owner_account_id") or record.get("account_id"),
                            record.get("project_id"), record.get("conversation_id"),
                            record.get("trace_id") or envelope.get("trace_id"),
                            json.dumps(record, ensure_ascii=False), created_at, timestamp,
                        ),
                    )
                db.execute(
                    "INSERT INTO data_record_events VALUES(?,?,?,?,?,?,?,?)",
                    (
                        str(uuid4()), dataset, record_id, operation,
                        envelope.get("trace_id"), actor_id,
                        json.dumps(record, ensure_ascii=False), timestamp,
                    ),
                )
                saved.append({"dataset": dataset, "record_id": record_id, "operation": operation})
    return {"state": "persisted", "storage": "foundation-data", "count": len(saved), "items": saved}


def _read(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    dataset = str(payload.get("dataset") or "")
    record_id = str(payload.get("record_id") or "")
    if not dataset or not record_id:
        raise ValueError("dataset and record_id are required")
    tenant_id = str(payload.get("tenant_id") or (envelope.get("actor") or {}).get("tenant_id") or "default")
    with connect() as db:
        row = db.execute(
            "SELECT payload_json FROM data_records WHERE dataset=? AND record_id=? AND tenant_id=? AND deleted_at IS NULL",
            (dataset, record_id, tenant_id),
        ).fetchone()
    return {"state": "found" if row else "not_found", "dataset": dataset, "item": json.loads(row["payload_json"]) if row else None}


def _query(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    dataset = str(payload.get("dataset") or "")
    if not dataset:
        raise ValueError("dataset is required")
    tenant_id = str(payload.get("tenant_id") or (envelope.get("actor") or {}).get("tenant_id") or "default")
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    limit = min(max(int(payload.get("limit", 100)), 1), 500)
    items = _query_records(dataset, tenant_id, filters, limit)
    return {"state": "completed", "dataset": dataset, "count": len(items), "items": items}


def _query_records(dataset: str, tenant_id: str, filters: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    if not dataset:
        return []
    with connect() as db:
        rows = db.execute(
            "SELECT payload_json FROM data_records WHERE dataset=? AND tenant_id=? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT ?",
            (dataset, tenant_id, limit * 5),
        ).fetchall()
    items = [json.loads(row["payload_json"]) for row in rows]
    if filters:
        items = [item for item in items if all(item.get(key) == value for key, value in filters.items())]
    return items[:limit]


def _register_source(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    source_id = str(payload.get("source_id") or uuid4())
    tenant_id = str(payload.get("tenant_id") or (envelope.get("actor") or {}).get("tenant_id") or "default")
    source_type = str(payload.get("source_type") or "unknown")
    timestamp = now()
    with connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO data_sources VALUES(?,?,?,?,?,?)",
            (source_id, tenant_id, source_type, json.dumps(payload.get("config") or {}, ensure_ascii=False), timestamp, timestamp),
        )
    return {"state": "registered", "source_id": source_id, "source_type": source_type}


def _infer_record_id(record: dict[str, Any]) -> Any:
    for key in (
        "message_id", "file_id", "task_id", "call_id", "session_id",
        "binding_id", "snapshot_id", "asset_id", "conversation_id", "account_id",
    ):
        if record.get(key):
            return record[key]
    return None
