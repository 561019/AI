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
    "foundation_data.catalog.list",
    "foundation_data.access.trace",
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
        spec = _catalog_spec(dataset)
        if dataset in SENSITIVE_DATASETS or (spec and bool(spec["sensitive"])):
            handler.send(403, {"error": {"code": "SENSITIVE_DATASET_FORBIDDEN"}})
            return True
        tenant_id = (query.get("tenant_id") or ["web-workbench"])[0]
        limit = min(max(int((query.get("limit") or ["100"])[0]), 1), 50000)
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
        elif capability == "foundation_data.source.register":
            data = _register_source(envelope, payload)
        elif capability == "foundation_data.catalog.list":
            data = _catalog_list(envelope)
        else:
            data = _access_trace(envelope, payload)
    except PermissionError as exc:
        handler.send(403, standard_response(envelope, "failed", error={"code": "FOUNDATION_DATA_ACCESS_DENIED", "message": str(exc)}))
        return
    except ValueError as exc:
        handler.send(422, standard_response(envelope, "failed", error={"code": "FOUNDATION_DATA_INPUT_INVALID", "message": str(exc)}))
        return
    except Exception as exc:
        handler.send(500, standard_response(envelope, "failed", error={"code": "FOUNDATION_DATA_INTERNAL_ERROR", "message": str(exc)}))
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
    default_tenant = str(actor.get("tenant_id") or "")
    actor_id = str(actor.get("user_id") or actor.get("actor_id") or "system")
    saved: list[dict[str, Any]] = []
    access_summaries: list[tuple[str, int]] = []
    with connect() as db:
        for write in writes:
            dataset = str(write.get("dataset") or "").strip()
            operation = str(write.get("operation") or "upsert").lower()
            records = write.get("records") or []
            if not dataset:
                raise ValueError("dataset is required")
            if operation not in {"insert", "update", "upsert", "delete"}:
                raise ValueError(f"unsupported operation: {operation}")
            spec = _authorize(envelope, dataset, "write")
            if not isinstance(records, list) or not records or any(not isinstance(item, dict) for item in records):
                raise ValueError(f"records are required for dataset {dataset}")
            for source in records:
                record = dict(source)
                record_id = str(record.get("record_id") or _infer_record_id(record) or uuid4())
                tenant_id = str(record.get("tenant_id") or default_tenant)
                if tenant_id != default_tenant and not _is_platform_admin(actor):
                    _deny(envelope, dataset, "write", "TENANT_SCOPE_MISMATCH", {"requested_tenant_id": tenant_id})
                _validate_project_scope(envelope, dataset, "write", record.get("project_id"))
                record.setdefault("record_id", record_id)
                record.setdefault("tenant_id", tenant_id)
                record.setdefault("trace_id", envelope.get("trace_id"))
                existing = db.execute(
                    "SELECT created_at,payload_json,record_version FROM data_records WHERE dataset=? AND tenant_id=? AND record_id=?",
                    (dataset, tenant_id, record_id),
                ).fetchone()
                if operation == "insert" and existing:
                    raise ValueError(f"record already exists: {dataset}/{record_id}")
                if operation == "update" and not existing:
                    raise ValueError(f"record does not exist: {dataset}/{record_id}")
                if operation in {"insert", "upsert"} and not existing:
                    required = json.loads(spec["required_fields_json"])
                    missing = [field for field in required if record.get(field) in (None, "")]
                    if missing:
                        raise ValueError(f"required fields missing for {dataset}: {', '.join(missing)}")
                expected_version = record.pop("expected_record_version", None)
                if existing and expected_version is not None and int(expected_version) != int(existing["record_version"]):
                    raise ValueError(f"record version conflict: {dataset}/{record_id}")
                if operation == "delete":
                    db.execute(
                        "UPDATE data_records SET deleted_at=?,updated_at=?,trace_id=?,record_version=record_version+1 WHERE dataset=? AND tenant_id=? AND record_id=?",
                        (timestamp, timestamp, envelope.get("trace_id"), dataset, tenant_id, record_id),
                    )
                    record_version = int(existing["record_version"]) + 1 if existing else None
                else:
                    if existing and operation == "update":
                        merged = json.loads(existing["payload_json"])
                        merged.update(record)
                        record = merged
                    created_at = existing["created_at"] if existing else timestamp
                    record_version = int(existing["record_version"]) + 1 if existing else 1
                    record["record_version"] = record_version
                    record.setdefault("classification", spec["classification"])
                    record.setdefault("retention_policy_id", spec["retention_policy_id"])
                    record.setdefault("schema_version", int(spec["schema_version"]))
                    db.execute(
                        """
                        INSERT INTO data_records(
                          dataset,record_id,tenant_id,owner_account_id,project_id,conversation_id,trace_id,
                          classification,retention_policy_id,schema_version,record_version,payload_json,
                          created_at,updated_at,deleted_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
                        ON CONFLICT(dataset,tenant_id,record_id) DO UPDATE SET
                          owner_account_id=excluded.owner_account_id,
                          project_id=excluded.project_id,
                          conversation_id=excluded.conversation_id,
                          trace_id=excluded.trace_id,
                          classification=excluded.classification,
                          retention_policy_id=excluded.retention_policy_id,
                          schema_version=excluded.schema_version,
                          record_version=excluded.record_version,
                          payload_json=excluded.payload_json,
                          updated_at=excluded.updated_at,
                          deleted_at=NULL
                        """,
                        (
                            dataset, record_id, tenant_id,
                            record.get("owner_account_id") or record.get("account_id"),
                            record.get("project_id"), record.get("conversation_id"),
                            record.get("trace_id") or envelope.get("trace_id"), spec["classification"],
                            spec["retention_policy_id"], int(spec["schema_version"]), record_version,
                            json.dumps(record, ensure_ascii=False), created_at, timestamp,
                        ),
                    )
                db.execute(
                    "INSERT INTO data_record_events VALUES(?,?,?,?,?,?,?,?)",
                    (
                        str(uuid4()), dataset, record_id, operation,
                        envelope.get("trace_id"), actor_id,
                        json.dumps(_redact_event_payload(dataset, record), ensure_ascii=False), timestamp,
                    ),
                )
                saved.append({"dataset": dataset, "record_id": record_id, "operation": operation, "record_version": record_version})
            access_summaries.append((dataset, len(records)))
    for dataset, record_count in access_summaries:
        _allow(envelope, dataset, "write", {"records": record_count})
    preview_limit = 50
    return {
        "state": "persisted",
        "storage": "foundation-data",
        "count": len(saved),
        "items": saved[:preview_limit],
        "items_truncated": len(saved) > preview_limit,
        "omitted_item_count": max(len(saved) - preview_limit, 0),
        "write_summary": [
            {"dataset": dataset, "record_count": record_count}
            for dataset, record_count in access_summaries
        ],
    }


def _read(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    dataset = str(payload.get("dataset") or "")
    record_id = str(payload.get("record_id") or "")
    if not dataset or not record_id:
        raise ValueError("dataset and record_id are required")
    _authorize(envelope, dataset, "read")
    tenant_id = _tenant_for_request(envelope, payload)
    with connect() as db:
        row = db.execute(
            "SELECT payload_json,project_id FROM data_records WHERE dataset=? AND record_id=? AND tenant_id=? AND deleted_at IS NULL",
            (dataset, record_id, tenant_id),
        ).fetchone()
    if row:
        _validate_project_scope(envelope, dataset, "read", row["project_id"])
    decision_id = _allow(envelope, dataset, "read", {"record_id": record_id, "found": bool(row)})
    return {
        "state": "found" if row else "not_found", "dataset": dataset,
        "item": _sanitize_item(dataset, json.loads(row["payload_json"])) if row else None,
        "permission_decision_id": decision_id,
    }


def _query(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    dataset = str(payload.get("dataset") or "")
    if not dataset:
        raise ValueError("dataset is required")
    _authorize(envelope, dataset, "read")
    tenant_id = _tenant_for_request(envelope, payload)
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    limit = min(max(int(payload.get("limit", 100)), 1), 50000)
    items = _query_records(dataset, tenant_id, filters, limit)
    allowed_projects = _allowed_projects(envelope.get("actor") or {})
    if allowed_projects is not None:
        items = [item for item in items if not item.get("project_id") or str(item.get("project_id")) in allowed_projects]
    items = [_sanitize_item(dataset, item) for item in items]
    if payload.get("compact") or dataset == "conversation_messages":
        items = [_compact_item(dataset, item) for item in items]
    decision_id = _allow(envelope, dataset, "read", {"count": len(items), "filters": filters})
    return {"state": "completed", "dataset": dataset, "count": len(items), "items": items, "permission_decision_id": decision_id}


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
        items = [item for item in items if all(_filter_matches(item, key, value) for key, value in filters.items())]
    return items[:limit]


def _filter_matches(item: dict[str, Any], key: str, expected: Any) -> bool:
    actual: Any = item
    for part in str(key).split("."):
        if not isinstance(actual, dict):
            actual = None
            break
        actual = actual.get(part)
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


def _register_source(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    actor = envelope.get("actor") or {}
    if not actor.get("authenticated"):
        raise PermissionError("AUTHENTICATION_REQUIRED")
    source_id = str(payload.get("source_id") or uuid4())
    tenant_id = _tenant_for_request(envelope, payload)
    source_type = str(payload.get("source_type") or "unknown")
    timestamp = now()
    safe_config = _redact_mapping(payload.get("config") or {})
    with connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO data_sources VALUES(?,?,?,?,?,?)",
            (source_id, tenant_id, source_type, json.dumps(safe_config, ensure_ascii=False), timestamp, timestamp),
        )
    return {"state": "registered", "source_id": source_id, "source_type": source_type}


def _catalog_list(envelope: dict[str, Any]) -> dict[str, Any]:
    actor = envelope.get("actor") or {}
    if not actor.get("authenticated"):
        raise PermissionError("AUTHENTICATION_REQUIRED")
    with connect() as db:
        rows = db.execute(
            "SELECT dataset,owner_module,classification,retention_policy_id,sensitive,schema_version FROM dataset_catalog WHERE enabled=1 ORDER BY dataset"
        ).fetchall()
    return {"state": "completed", "items": [dict(row) for row in rows]}


def _access_trace(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    actor = envelope.get("actor") or {}
    if not actor.get("authenticated"):
        raise PermissionError("AUTHENTICATION_REQUIRED")
    trace_id = str(payload.get("trace_id") or envelope.get("trace_id") or "")
    with connect() as db:
        if _is_platform_admin(actor):
            rows = db.execute("SELECT * FROM data_access_decisions WHERE trace_id=? ORDER BY created_at", (trace_id,)).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM data_access_decisions WHERE trace_id=? AND tenant_id=? ORDER BY created_at",
                (trace_id, str(actor.get("tenant_id"))),
            ).fetchall()
    return {"state": "completed", "trace_id": trace_id, "items": [dict(row) for row in rows]}


def _catalog_spec(dataset: str):
    with connect() as db:
        return db.execute("SELECT * FROM dataset_catalog WHERE dataset=? AND enabled=1", (dataset,)).fetchone()


def _authorize(envelope: dict[str, Any], dataset: str, action: str):
    spec = _catalog_spec(dataset)
    if not spec:
        _deny(envelope, dataset, action, "DATASET_NOT_REGISTERED", {})
    source_module = _authorization_source_module(envelope, action, dataset)
    allowed = json.loads(spec["allowed_readers_json"] if action == "read" else spec["allowed_writers_json"])
    if source_module not in allowed and source_module not in {"foundation-gateway", "foundation-data"}:
        _deny(envelope, dataset, action, "SOURCE_MODULE_NOT_ALLOWED", {"source_module": source_module})
    actor = envelope.get("actor") or {}
    if not actor.get("tenant_id"):
        _deny(envelope, dataset, action, "TENANT_CONTEXT_REQUIRED", {})
    if not actor.get("authenticated", False) and source_module != "account-gateway":
        _deny(envelope, dataset, action, "AUTHENTICATION_REQUIRED", {})
    return spec


def _tenant_for_request(envelope: dict[str, Any], payload: dict[str, Any]) -> str:
    actor = envelope.get("actor") or {}
    actor_tenant = str(actor.get("tenant_id") or "")
    requested = str(payload.get("tenant_id") or actor_tenant)
    if requested != actor_tenant and not _is_platform_admin(actor):
        _deny(envelope, str(payload.get("dataset") or "unknown"), "read", "TENANT_SCOPE_MISMATCH", {"requested_tenant_id": requested})
    return requested


def _allowed_projects(actor: dict[str, Any]) -> set[str] | None:
    values = actor.get("allowed_project_ids") or actor.get("project_ids")
    return None if values is None else {str(value) for value in values}


def _validate_project_scope(envelope: dict[str, Any], dataset: str, action: str, project_id: Any) -> None:
    if not project_id:
        return
    actor = envelope.get("actor") or {}
    allowed = _allowed_projects(actor)
    if allowed is not None and str(project_id) not in allowed and not _is_platform_admin(actor):
        _deny(envelope, dataset, action, "PROJECT_SCOPE_DENIED", {"project_id": project_id})


def _is_platform_admin(actor: dict[str, Any]) -> bool:
    roles = actor.get("roles") or ([actor.get("role")] if actor.get("role") else [])
    return any(str(role).lower() in {"platform_admin", "平台管理员"} for role in roles)


def _decision(envelope: dict[str, Any], dataset: str, action: str, effect: str, reason: str, scope: dict[str, Any]) -> str:
    decision_id = str(uuid4())
    actor = envelope.get("actor") or {}
    source_module = _authorization_source_module(envelope, action, dataset)
    delegated = _delegated_requesting_module(envelope)
    if delegated:
        scope = {**scope, "requesting_module": delegated}
    with connect() as db:
        db.execute(
            "INSERT INTO data_access_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                decision_id, str(envelope.get("trace_id") or "untraced"), str(actor.get("tenant_id") or "missing"),
                str(actor.get("user_id") or actor.get("actor_id") or "anonymous"), source_module,
                dataset, action, effect, reason, json.dumps(scope, ensure_ascii=False), now(),
            ),
        )
    return decision_id


def _deny(envelope: dict[str, Any], dataset: str, action: str, reason: str, scope: dict[str, Any]) -> None:
    decision_id = _decision(envelope, dataset, action, "deny", reason, scope)
    raise PermissionError(f"{reason}; decision_id={decision_id}")


def _allow(envelope: dict[str, Any], dataset: str, action: str, scope: dict[str, Any]) -> str:
    return _decision(envelope, dataset, action, "allow", "DATA_SCOPE_MATCHED", scope)


def _sanitize_item(dataset: str, item: dict[str, Any]) -> dict[str, Any]:
    if dataset == "accounts":
        return {key: value for key, value in item.items() if key not in {"password", "password_hash", "salt"}}
    return item


def _redact_event_payload(dataset: str, item: dict[str, Any]) -> dict[str, Any]:
    if dataset in SENSITIVE_DATASETS:
        return {"record_id": item.get("record_id"), "redacted": True}
    return _redact_mapping(item)


def _redact_mapping(value: Any) -> Any:
    sensitive = {"password", "password_hash", "salt", "token", "access_token", "refresh_token", "api_key", "secret", "authorization"}
    if isinstance(value, dict):
        return {key: ("***REDACTED***" if key.lower() in sensitive else _redact_mapping(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_mapping(item) for item in value]
    return value


def _effective_source_module(envelope: dict[str, Any]) -> str:
    source_module = str((envelope.get("source") or {}).get("module") or "unknown")
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    delegated = str(payload.get("_requesting_module") or "")
    return delegated if source_module == "data-operation" and delegated else source_module


def _authorization_source_module(envelope: dict[str, Any], action: str, dataset: str = "") -> str:
    source_module = str((envelope.get("source") or {}).get("module") or "unknown")
    if source_module == "data-operation" and action == "read":
        delegated = _delegated_requesting_module(envelope)
        if delegated == "account-gateway" and dataset in {
            "accounts",
            "account_credentials",
            "account_role_bindings",
            "account_sessions",
        }:
            return delegated
        return "data-operation"
    return _effective_source_module(envelope)


def _delegated_requesting_module(envelope: dict[str, Any]) -> str:
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    return str(payload.get("_requesting_module") or "")


def _infer_record_id(record: dict[str, Any]) -> Any:
    for key in (
        "message_id", "file_id", "task_id", "call_id", "session_id", "workflow_instance_id",
        "node_instance_id", "human_task_id", "confirmation_id", "binding_id", "snapshot_id",
        "asset_id", "conversation_id", "account_id", "object_id", "event_id",
        "knowledge_source_id", "chunk_id", "index_id",
    ):
        if record.get(key):
            return record[key]
    return None


def _compact_item(dataset: str, item: dict[str, Any]) -> dict[str, Any]:
    if dataset != "conversation_messages":
        return item
    compact = {
        key: item.get(key)
        for key in (
            "message_id", "record_id", "conversation_id", "project_id", "owner_account_id",
            "tenant_id", "role", "content_type", "content_text", "task_id", "trace_id", "created_at", "updated_at",
        )
        if item.get(key) not in (None, "")
    }
    compact["content"] = _compact_message_content(item.get("content"))
    return compact


def _compact_message_content(content: Any) -> Any:
    if not isinstance(content, dict):
        return content
    data = content.get("data") if isinstance(content.get("data"), dict) else content
    slim_data = {}
    for key in ("selected_capability", "provider_module", "intent_tasks", "tasks", "uploaded_documents"):
        if data.get(key) not in (None, "", []):
            slim_data[key] = data.get(key)
    if isinstance(data.get("workflow_instance"), dict):
        workflow = data["workflow_instance"]
        slim_data["workflow_instance"] = {
            key: workflow.get(key)
            for key in ("instance_id", "route_type", "status")
            if workflow.get(key) not in (None, "")
        }
    capability_result = data.get("capability_result") if isinstance(data.get("capability_result"), dict) else {}
    slim_capability = {
        key: capability_result.get(key)
        for key in ("state", "summary_cn", "summary", "answer", "user_answer")
        if capability_result.get(key) not in (None, "")
    }
    if slim_capability:
        slim_data["capability_result"] = slim_capability
    return slim_data if slim_data else content
