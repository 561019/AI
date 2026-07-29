from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from framework.module_catalog import ALL_MODULES, additional_capabilities
from framework.data_catalog import DATASETS


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("PLATFORM_DB_PATH", ROOT / "framework" / "data" / "foundation_data" / "platform_data.db"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # SQLite permits one writer. Wait for an active transaction rather than
    # failing a request while another framework service commits.
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def initialize() -> None:
    with connect() as db:
        # WAL is a database-wide setting. It must not be negotiated again for
        # every HTTP request connection in every service process.
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
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
            CREATE INDEX IF NOT EXISTS idx_interface_calls_created_at
              ON interface_calls(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_interface_calls_trace_created_at
              ON interface_calls(trace_id, created_at);
            CREATE TABLE IF NOT EXISTS data_records (
              dataset TEXT NOT NULL,
              record_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL,
              owner_account_id TEXT,
              project_id TEXT,
              conversation_id TEXT,
              trace_id TEXT,
              classification TEXT NOT NULL DEFAULT 'internal',
              retention_policy_id TEXT NOT NULL DEFAULT 'business-default',
              schema_version INTEGER NOT NULL DEFAULT 1,
              record_version INTEGER NOT NULL DEFAULT 1,
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
            CREATE TABLE IF NOT EXISTS dataset_catalog (
              dataset TEXT PRIMARY KEY,
              owner_module TEXT NOT NULL,
              classification TEXT NOT NULL,
              retention_policy_id TEXT NOT NULL,
              sensitive INTEGER NOT NULL DEFAULT 0,
              allowed_readers_json TEXT NOT NULL,
              allowed_writers_json TEXT NOT NULL,
              required_fields_json TEXT NOT NULL,
              schema_version INTEGER NOT NULL DEFAULT 1,
              enabled INTEGER NOT NULL DEFAULT 1,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS data_access_decisions (
              decision_id TEXT PRIMARY KEY,
              trace_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL,
              actor_id TEXT NOT NULL,
              source_module TEXT NOT NULL,
              dataset TEXT NOT NULL,
              action TEXT NOT NULL,
              effect TEXT NOT NULL,
              reason_code TEXT NOT NULL,
              scope_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_data_access_trace
              ON data_access_decisions(trace_id, created_at);
            """
        )
        _ensure_column(db, "data_records", "classification", "TEXT NOT NULL DEFAULT 'internal'")
        _ensure_column(db, "data_records", "retention_policy_id", "TEXT NOT NULL DEFAULT 'business-default'")
        _ensure_column(db, "data_records", "schema_version", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(db, "data_records", "record_version", "INTEGER NOT NULL DEFAULT 1")
        seed_dataset_catalog(db)
        seed_capabilities(db)


def _ensure_column(db: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    existing = {str(row["name"]) for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def seed_dataset_catalog(db: sqlite3.Connection) -> None:
    timestamp = now()
    db.executemany(
        """
        INSERT INTO dataset_catalog(
          dataset,owner_module,classification,retention_policy_id,sensitive,
          allowed_readers_json,allowed_writers_json,required_fields_json,schema_version,enabled,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,1,1,?)
        ON CONFLICT(dataset) DO UPDATE SET
          owner_module=excluded.owner_module,
          classification=excluded.classification,
          retention_policy_id=excluded.retention_policy_id,
          sensitive=excluded.sensitive,
          allowed_readers_json=excluded.allowed_readers_json,
          allowed_writers_json=excluded.allowed_writers_json,
          required_fields_json=excluded.required_fields_json,
          updated_at=excluded.updated_at
        """,
        [
            (
                item.code, item.owner_module, item.classification, item.retention_policy,
                int(item.sensitive), json.dumps(item.allowed_readers), json.dumps(item.allowed_writers),
                json.dumps(item.required_fields), timestamp,
            )
            for item in DATASETS
        ],
    )


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
    existing_codes = {row[0] for row in rows}
    for module in ALL_MODULES:
        for capability in module.capabilities:
            if capability in existing_codes:
                continue
            rows.append((
                capability,
                module.layer,
                module.code,
                f"http://127.0.0.1:{module.port}{module.interface}",
                "sync",
                "capability.invoke",
                "0.1",
                1,
            ))
            existing_codes.add(capability)
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


def update_task(task_id: str, *, state: str, progress: int | None = None, result: Any = None, confirmation: Any = None, error: Any = None, clear_error: bool = False, sequence: int | None = None) -> bool:
    with connect() as db:
        row = db.execute("SELECT sequence FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return False
        if sequence is not None and sequence <= int(row["sequence"]):
            return True
        db.execute(
            "UPDATE tasks SET state=?,progress=COALESCE(?,progress),result_json=COALESCE(?,result_json),confirmation_json=COALESCE(?,confirmation_json),error_json=CASE WHEN ? THEN NULL ELSE COALESCE(?,error_json) END,sequence=COALESCE(?,sequence),updated_at=? WHERE task_id=?",
            (state, progress, _json(result), _json(confirmation), clear_error, _json(error), sequence, now(), task_id),
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
            (call_id, trace_id, source.get("layer"), source.get("module"), target.get("layer"), target.get("module"), capability, method, url, _json(_redact_sensitive(request)), _json(_redact_sensitive(response)), status_code, round(duration_ms, 2), now()),
        )
    return call_id


def get_trace_calls(trace_id: str, *, call_id: str | None = None, max_payload_chars: int | None = None) -> list[dict[str, Any]]:
    with connect() as db:
        if call_id:
            rows = db.execute(
                "SELECT * FROM interface_calls WHERE trace_id=? AND call_id=? ORDER BY created_at, rowid",
                (trace_id, call_id),
            ).fetchall()
        else:
            rows = db.execute("SELECT * FROM interface_calls WHERE trace_id=? ORDER BY created_at, rowid", (trace_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["request"] = _load_audit_payload(item.pop("request_json"), max_payload_chars)
        item["response"] = _load_audit_payload(item.pop("response_json"), max_payload_chars)
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


def _load_audit_payload(value: str | None, max_chars: int | None) -> Any:
    if value is None:
        return None
    if max_chars is not None and len(value) > max_chars:
        return {
            "_truncated": True,
            "size_chars": len(value),
            "preview": value[:max_chars],
        }
    return json.loads(value)


def _redact_sensitive(value: Any) -> Any:
    sensitive_keys = {
        "password", "password_hash", "salt", "token", "access_token", "refresh_token",
        "api_key", "apikey", "secret", "authorization", "cookie", "set-cookie",
    }
    if isinstance(value, dict):
        return {
            key: ("***REDACTED***" if str(key).lower() in sensitive_keys else _redact_sensitive(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value
