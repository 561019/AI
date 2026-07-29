from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import get_settings


class AuditRepository:
    """审计日志仓库（SQLite，hash 链防篡改）—— 简化版仅用于 check 流程。"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or get_settings().db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_db(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"
        with self._connect() as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))
            self._ensure_columns(conn)

    def _ensure_columns(self, conn: sqlite3.Connection) -> None:
        def add_missing(table: str, required: Dict[str, str]) -> None:
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for col, typ in required.items():
                if col not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")

        add_missing("security_audit_log", {
            "idempotency_key": "TEXT", "callback_url": "TEXT", "code": "TEXT",
            "audit_level": "TEXT", "previous_hash": "TEXT", "payload_hash": "TEXT",
            "integrity_hash": "TEXT", "input_text": "TEXT", "output_text": "TEXT",
        })
        conn.execute("CREATE INDEX IF NOT EXISTS idx_security_audit_idempotency ON security_audit_log(idempotency_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_security_audit_integrity ON security_audit_log(integrity_hash)")

    # ── insert ──────────────────────────────────────────────────────
    def insert_audit_log(self, record: Dict[str, Any]) -> None:
        columns_without_hash = [
            "audit_id", "request_id", "trace_id", "idempotency_key", "callback_url",
            "stage", "caller_module", "scene_code", "account_id", "real_person_id",
            "active_position_id", "domain_id", "agent_id", "responsible_person_id",
            "action_type", "operation", "target_system", "decision", "code", "reason",
            "hit_policy_ids", "need_masking", "need_human_confirm", "audit_level",
            "risk_level", "input_text", "output_text", "created_at",
        ]
        stored_record = {col: self._db_value(record.get(col)) for col in columns_without_hash}
        previous_hash = self._latest_integrity_hash()
        payload_hash = self._payload_hash(stored_record)
        integrity_hash = self._integrity_hash(previous_hash, payload_hash, record.get("audit_id"), record.get("created_at"))
        stored_record.update({"previous_hash": previous_hash, "payload_hash": payload_hash, "integrity_hash": integrity_hash})

        columns = columns_without_hash + ["previous_hash", "payload_hash", "integrity_hash"]
        values = [stored_record.get(col) for col in columns]
        placeholders = ",".join(["?"] * len(columns))
        sql = f"INSERT INTO security_audit_log ({','.join(columns)}) VALUES ({placeholders})"
        with self._connect() as conn:
            conn.execute(sql, values)
            conn.commit()

    def insert_trace_span(self, record: Dict[str, Any]) -> None:
        columns = ["span_id", "trace_id", "audit_id", "parent_span_id", "span_type", "module", "stage", "decision", "code", "latency_ms", "input_json", "output_json", "created_at"]
        values = [self._db_value(record.get(col)) for col in columns]
        placeholders = ",".join(["?"] * len(columns))
        with self._connect() as conn:
            conn.execute(f"INSERT INTO security_trace_span ({','.join(columns)}) VALUES ({placeholders})", values)
            conn.commit()

    def insert_observation(self, record: Dict[str, Any]) -> None:
        columns = ["observation_id", "span_id", "trace_id", "audit_id", "observation_type", "name", "level", "payload_json", "created_at"]
        values = [self._db_value(record.get(col)) for col in columns]
        placeholders = ",".join(["?"] * len(columns))
        with self._connect() as conn:
            conn.execute(f"INSERT INTO security_observation ({','.join(columns)}) VALUES ({placeholders})", values)
            conn.commit()

    # ── query ───────────────────────────────────────────────────────
    def list_audit_logs(self, trace_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            if trace_id:
                rows = conn.execute("SELECT * FROM security_audit_log WHERE trace_id=? ORDER BY created_at DESC LIMIT ?", (trace_id, limit)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM security_audit_log ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(row) for row in rows]

    def list_trace_spans(self, trace_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM security_trace_span WHERE trace_id=? ORDER BY created_at ASC", (trace_id,)).fetchall()
            return [dict(row) for row in rows]

    def list_observations(self, trace_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM security_observation WHERE trace_id=? ORDER BY created_at ASC", (trace_id,)).fetchall()
            return [dict(row) for row in rows]

    def search_audit_logs(self, filters: Dict[str, Any], limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        where = []
        params: List[Any] = []
        exact_fields = ["trace_id", "audit_id", "stage", "caller_module", "scene_code", "real_person_id", "decision", "code", "risk_level", "audit_level", "operation", "target_system"]
        for field in exact_fields:
            value = filters.get(field)
            if value:
                where.append(f"{field}=?")
                params.append(value)
        if filters.get("from_time"):
            where.append("created_at>=?")
            params.append(filters["from_time"])
        if filters.get("to_time"):
            where.append("created_at<=?")
            params.append(filters["to_time"])
        if filters.get("q"):
            where.append("(reason LIKE ? OR operation LIKE ? OR scene_code LIKE ? OR caller_module LIKE ? OR code LIKE ? OR input_text LIKE ?)")
            like = f"%{filters['q']}%"
            params.extend([like, like, like, like, like, like])
        where_sql = " WHERE " + " AND ".join(where) if where else ""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            total_row = conn.execute(f"SELECT COUNT(*) AS c FROM security_audit_log{where_sql}", params).fetchone()
            rows = conn.execute(f"SELECT * FROM security_audit_log{where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
            return {"total": total_row["c"] if total_row else 0, "items": [dict(row) for row in rows]}

    def verify_audit_integrity(self, limit: int = 500) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM security_audit_log ORDER BY rowid ASC LIMIT ?", (limit,)).fetchall()
        previous = "GENESIS"
        broken: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            stored_prev = record.get("previous_hash")
            stored_payload = record.get("payload_hash")
            stored_integrity = record.get("integrity_hash")
            payload_record = {k: record.get(k) for k in [
                "audit_id", "request_id", "trace_id", "idempotency_key", "callback_url", "stage", "caller_module", "scene_code",
                "account_id", "real_person_id", "active_position_id", "domain_id", "agent_id", "responsible_person_id",
                "action_type", "operation", "target_system", "decision", "code", "reason", "hit_policy_ids",
                "need_masking", "need_human_confirm", "audit_level", "risk_level", "input_text", "output_text", "created_at",
            ]}
            expected_payload = self._payload_hash(payload_record)
            expected_integrity = self._integrity_hash(previous, expected_payload, record.get("audit_id"), record.get("created_at"))
            ok = stored_prev == previous and stored_payload == expected_payload and stored_integrity == expected_integrity
            if not ok:
                broken.append({
                    "audit_id": record.get("audit_id"),
                    "expected_previous_hash": previous,
                    "stored_previous_hash": stored_prev,
                    "payload_hash_ok": stored_payload == expected_payload,
                    "integrity_hash_ok": stored_integrity == expected_integrity,
                })
            previous = stored_integrity or previous
        return {"checked": len(rows), "ok": not broken, "broken_rows": broken, "last_hash": previous}

    def get_output_files_for_traces(self, trace_ids: list) -> dict:
        if not trace_ids:
            return {}
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            placeholders = ",".join(["?"] * len(trace_ids))
            rows = conn.execute(
                f"SELECT trace_id, payload_json FROM security_observation WHERE observation_type='ai_output_file' AND trace_id IN ({placeholders}) ORDER BY created_at ASC",
                trace_ids,
            ).fetchall()
        result: dict = {}
        for row in rows:
            tid = row["trace_id"]
            if tid not in result:
                result[tid] = []
            try:
                payload = json.loads(row["payload_json"])
                result[tid].append({"name": payload.get("file_name", ""), "type": payload.get("file_type", "")})
            except Exception:
                pass
        return result

    # ── hash helpers ────────────────────────────────────────────────
    def _latest_integrity_hash(self) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT integrity_hash FROM security_audit_log ORDER BY rowid DESC LIMIT 1").fetchone()
            return row[0] if row and row[0] else "GENESIS"

    def _payload_hash(self, record: Dict[str, Any]) -> str:
        payload = {k: self._json_safe(v) for k, v in record.items() if k not in {"previous_hash", "payload_hash", "integrity_hash"}}
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _integrity_hash(self, previous_hash: str, payload_hash: str, audit_id: Any, created_at: Any) -> str:
        raw = f"{previous_hash}|{payload_hash}|{audit_id}|{created_at}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (dict, list, str, int, float)) or value is None:
            return value
        return str(value)

    def _db_value(self, value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, bool):
            return int(value)
        return value
