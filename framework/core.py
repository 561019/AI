from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from framework.module_catalog import additional_capabilities


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("PLATFORM_DB_PATH", ROOT / "framework" / "data" / "foundation_data" / "platform_data.db"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def initialize() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
              task_id TEXT PRIMARY KEY,
              trace_id TEXT NOT NULL,
              request_id TEXT NOT NULL,
              state TEXT NOT NULL,
              progress INTEGER NOT NULL DEFAULT 0,
              result_json TEXT,
              confirmation_json TEXT,
              error_json TEXT,
              sequence INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS idempotency (
              scope TEXT NOT NULL,
              idem_key TEXT NOT NULL,
              request_hash TEXT NOT NULL,
              response_json TEXT NOT NULL,
              PRIMARY KEY (scope, idem_key)
            );
            CREATE TABLE IF NOT EXISTS capabilities (
              capability_code TEXT PRIMARY KEY,
              layer TEXT NOT NULL,
              provider_module TEXT NOT NULL,
              endpoint TEXT NOT NULL,
              execution_mode TEXT NOT NULL,
              required_action TEXT NOT NULL,
              version TEXT NOT NULL,
              enabled INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS interface_calls (
              call_id TEXT PRIMARY KEY,
              trace_id TEXT NOT NULL,
              source_layer TEXT,
              source_module TEXT,
              target_layer TEXT,
              target_module TEXT,
              capability TEXT,
              method TEXT NOT NULL,
              url TEXT NOT NULL,
              request_json TEXT,
              response_json TEXT,
              status_code INTEGER,
              duration_ms REAL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS data_records (
              dataset TEXT NOT NULL,
              record_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL,
              owner_account_id TEXT,
              project_id TEXT,
              conversation_id TEXT,
              trace_id TEXT,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              deleted_at TEXT,
              PRIMARY KEY (dataset, tenant_id, record_id)
            );
            CREATE INDEX IF NOT EXISTS idx_data_records_tenant_dataset
              ON data_records(tenant_id, dataset, updated_at);
            CREATE INDEX IF NOT EXISTS idx_data_records_conversation
              ON data_records(conversation_id, dataset, updated_at);
            CREATE INDEX IF NOT EXISTS idx_data_records_trace
              ON data_records(trace_id, updated_at);
            CREATE TABLE IF NOT EXISTS data_record_events (
              event_id TEXT PRIMARY KEY,
              dataset TEXT NOT NULL,
              record_id TEXT NOT NULL,
              operation TEXT NOT NULL,
              trace_id TEXT,
              actor_id TEXT,
              payload_json TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS data_sources (
              source_id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              source_type TEXT NOT NULL,
              config_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        seed_capabilities(db)


def seed_capabilities(db: sqlite3.Connection) -> None:
    rows = [
        ("intent.analyze", "business_engine", "intent-adapter", "http://127.0.0.1:8000/api/v1/intent/analyze", "async", "capability.invoke", "0.1", 1),
        ("workflow.execute", "business_engine", "workflow-execution", "http://127.0.0.1:8020/api/v1/workflows/executions", "async", "capability.invoke", "0.1", 1),
        ("rule.calculate", "business_engine", "rule-adapter", "http://127.0.0.1:8010/api/v1/rules/instructions", "sync", "capability.invoke", "0.1", 1),
        ("content.generate", "business_engine", "content-adapter", "http://127.0.0.1:8011/api/v1/content/instructions", "sync", "capability.invoke", "0.1", 1),
        ("permissions.check", "foundation", "permission-adapter", "http://127.0.0.1:8001/api/v1/permissions/check", "sync", "capability.invoke", "0.1", 1),
        ("model.respond", "foundation", "model-dispatcher", "http://127.0.0.1:8002/api/v1/models/responses", "sync", "capability.invoke", "0.1", 1),
        ("template.retrieve", "foundation", "template-management", "http://127.0.0.1:8004/api/v1/templates/instructions", "sync", "capability.invoke", "1.0", 1),
        ("template.list", "foundation", "template-management", "http://127.0.0.1:8004/api/v1/templates/instructions", "sync", "capability.invoke", "1.0", 1),
        ("template.validate", "foundation", "template-management", "http://127.0.0.1:8004/api/v1/templates/instructions", "sync", "capability.invoke", "1.0", 1),
        ("template.register_draft", "foundation", "template-management", "http://127.0.0.1:8004/api/v1/templates/instructions", "sync", "capability.invoke", "1.0", 1),
        ("template.update_draft", "foundation", "template-management", "http://127.0.0.1:8004/api/v1/templates/instructions", "sync", "capability.invoke", "1.0", 1),
        ("template.publish", "foundation", "template-management", "http://127.0.0.1:8004/api/v1/templates/instructions", "sync", "capability.invoke", "1.0", 1),
        ("template.disable", "foundation", "template-management", "http://127.0.0.1:8004/api/v1/templates/instructions", "sync", "capability.invoke", "1.0", 1),
    ]
    rows.extend(additional_capabilities())
    codes = [row[0] for row in rows]
    placeholders = ",".join("?" for _ in codes)
    db.execute(f"DELETE FROM capabilities WHERE capability_code NOT IN ({placeholders})", codes)
    db.executemany("INSERT OR REPLACE INTO capabilities VALUES (?,?,?,?,?,?,?,?)", rows)


def digest(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def idempotent_get(scope: str, key: str, request: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    request_hash = digest(request)
    with connect() as db:
        row = db.execute("SELECT request_hash,response_json FROM idempotency WHERE scope=? AND idem_key=?", (scope, key)).fetchone()
    if not row:
        return "new", None
    if row["request_hash"] != request_hash:
        return "conflict", None
    return "replay", json.loads(row["response_json"])


def idempotent_put(scope: str, key: str, request: dict[str, Any], response: dict[str, Any]) -> None:
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO idempotency VALUES (?,?,?,?)", (scope, key, digest(request), json.dumps(response, ensure_ascii=False)))


def create_task(trace_id: str, request_id: str) -> str:
    task_id = str(uuid4())
    timestamp = now()
    with connect() as db:
        db.execute("INSERT INTO tasks(task_id,trace_id,request_id,state,created_at,updated_at) VALUES (?,?,?,?,?,?)", (task_id, trace_id, request_id, "accepted", timestamp, timestamp))
    return task_id


def update_task(task_id: str, *, state: str, progress: int | None = None, result: Any = None, confirmation: Any = None, error: Any = None, sequence: int | None = None) -> bool:
    with connect() as db:
        row = db.execute("SELECT sequence FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return False
        if sequence is not None and sequence <= int(row["sequence"]):
            return True
        db.execute(
            "UPDATE tasks SET state=?,progress=COALESCE(?,progress),result_json=COALESCE(?,result_json),confirmation_json=COALESCE(?,confirmation_json),error_json=COALESCE(?,error_json),sequence=COALESCE(?,sequence),updated_at=? WHERE task_id=?",
            (state, progress, _json(result), _json(confirmation), _json(error), sequence, now(), task_id),
        )
    return True


def get_task(task_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    if not row:
        return None
    return {
        "task_id": row["task_id"], "trace_id": row["trace_id"], "state": row["state"],
        "progress": row["progress"], "result_ref": _load(row["result_json"]),
        "confirmation_ref": _load(row["confirmation_json"]), "error": _load(row["error_json"]),
        "updated_at": row["updated_at"],
    }


def get_latest_task_by_trace(trace_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            "SELECT task_id FROM tasks WHERE trace_id=? ORDER BY updated_at DESC, rowid DESC LIMIT 1",
            (trace_id,),
        ).fetchone()
    return get_task(row["task_id"]) if row else None


def resolve_capability(code: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM capabilities WHERE capability_code=? AND enabled=1", (code,)).fetchone()
    return dict(row) if row else None


def record_interface_call(*, trace_id: str, source: dict[str, Any], target: dict[str, Any], capability: str, method: str, url: str, request: Any, response: Any, status_code: int, duration_ms: float) -> str:
    call_id = str(uuid4())
    with connect() as db:
        db.execute(
            "INSERT INTO interface_calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (call_id, trace_id, source.get("layer"), source.get("module"), target.get("layer"), target.get("module"), capability, method, url, _json(request), _json(response), status_code, round(duration_ms, 2), now()),
        )
    return call_id


def get_trace_calls(trace_id: str) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT * FROM interface_calls WHERE trace_id=? ORDER BY created_at, rowid", (trace_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["request"] = _load(item.pop("request_json"))
        item["response"] = _load(item.pop("response_json"))
        result.append(item)
    return result


def standard_response(envelope: dict[str, Any], status: str, **kwargs: Any) -> dict[str, Any]:
    return {
        "status": status,
        "trace_id": envelope.get("trace_id", str(uuid4())),
        "request_id": envelope.get("request_id", str(uuid4())),
        "in_reply_to": envelope.get("message_id"),
        "data": kwargs.get("data"),
        "error": kwargs.get("error"),
        **({"task_id": kwargs["task_id"]} if kwargs.get("task_id") else {}),
        **({"progress": kwargs["progress"]} if "progress" in kwargs else {}),
        **({"status_url": kwargs["status_url"]} if kwargs.get("status_url") else {}),
    }


def validate_envelope(value: dict[str, Any]) -> list[str]:
    required = {"protocol_version", "message_id", "request_id", "trace_id", "source", "target", "actor", "request_type", "action", "payload", "expected_response", "idempotency_key"}
    missing = sorted(required.difference(value))
    if value.get("protocol_version") != "1.0":
        missing.append("protocol_version=1.0")
    return missing


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _load(value: str | None) -> Any:
    return None if value is None else json.loads(value)
