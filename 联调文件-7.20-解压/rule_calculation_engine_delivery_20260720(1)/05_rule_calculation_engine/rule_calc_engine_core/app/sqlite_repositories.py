from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .database import connect


class SQLitePlatformDataAdapter:
    """Development replacement for L1.7 storage and query services."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def capability_exists(self, capability_code: str) -> bool:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT 1 FROM capabilities WHERE capability_code = ?", (capability_code,)
            ).fetchone()
        return row is not None

    def list_published_capabilities(
        self, business_type: str, capability_code: str | None = None
    ) -> list[dict[str, Any]]:
        with connect(self.database_path) as connection:
            if capability_code:
                rows = connection.execute(
                    """SELECT * FROM capabilities
                       WHERE capability_code = ? AND scenario = ? AND status = 'published'
                       ORDER BY capability_code""",
                    (capability_code, business_type),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM capabilities
                       WHERE scenario = ? AND status = 'published'
                       ORDER BY capability_code""",
                    (business_type,),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_all_published_capabilities(self) -> list[dict[str, Any]]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """SELECT * FROM capabilities
                   WHERE status = 'published'
                   ORDER BY capability_code"""
            ).fetchall()
        return [dict(row) for row in rows]

    def list_published_rule_versions(self, capability_code: str) -> list[dict[str, Any]]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """SELECT rv.*, g.source_basis, g.review_role, g.reviewed_by,
                          g.reviewed_at, g.effective_at
                   FROM rule_versions rv
                   LEFT JOIN rule_version_governance g ON g.rule_version_id = rv.id
                   WHERE rv.capability_code = ? AND rv.status = 'published'
                   ORDER BY rv.id DESC""",
                (capability_code,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_draft(
        self,
        capability_code: str,
        rule_version: str,
        parameter_version: str,
        treatment_rule_version: str,
        payload: dict[str, Any],
        source_basis: str,
        review_role: str,
        entered_by: str,
    ) -> int:
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """INSERT INTO rule_versions
                   (capability_code, rule_version, parameter_version, treatment_rule_version, status, payload_json)
                   VALUES (?, ?, ?, ?, 'draft', ?)""",
                (capability_code, rule_version, parameter_version, treatment_rule_version, json.dumps(payload)),
            )
            rule_version_id = cursor.lastrowid
            connection.execute(
                """INSERT INTO rule_version_governance
                   (rule_version_id, source_basis, review_role, entered_by)
                   VALUES (?, ?, ?, ?)""",
                (rule_version_id, source_basis, review_role, entered_by),
            )
            self._insert_transition(
                connection,
                rule_version_id,
                capability_code,
                None,
                "draft",
                "create_draft",
                entered_by,
                "Draft entered from an approved source basis.",
            )
        return rule_version_id

    def get(self, rule_version_id: int) -> dict[str, Any] | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                """SELECT rv.*, g.source_basis, g.review_role, g.reviewed_by, g.reviewed_at, g.effective_at
                   FROM rule_versions rv
                   JOIN rule_version_governance g ON g.rule_version_id = rv.id
                   WHERE rv.id = ?""",
                (rule_version_id,),
            ).fetchone()
        return dict(row) if row else None

    def apply_transition(
        self,
        rule_version_id: int,
        capability_code: str,
        from_status: str,
        to_status: str,
        action: str,
        actor_id: str,
        comment: str,
        reviewed_at: str | None = None,
        effective_at: str | None = None,
        retire_previous_published: bool = False,
    ) -> None:
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                "UPDATE rule_versions SET status = ? WHERE id = ? AND status = ?",
                (to_status, rule_version_id, from_status),
            )
            if cursor.rowcount != 1:
                raise ValueError("Rule version status changed concurrently; reload before retrying.")
            if retire_previous_published:
                connection.execute(
                    """UPDATE rule_versions SET status = 'retired'
                       WHERE capability_code = ? AND status = 'published' AND id <> ?""",
                    (capability_code, rule_version_id),
                )
            if reviewed_at or effective_at:
                connection.execute(
                    """UPDATE rule_version_governance
                       SET reviewed_by = ?, reviewed_at = ?, effective_at = ?
                       WHERE rule_version_id = ?""",
                    (actor_id, reviewed_at, effective_at, rule_version_id),
                )
            self._insert_transition(
                connection,
                rule_version_id,
                capability_code,
                from_status,
                to_status,
                action,
                actor_id,
                comment,
            )

    def save_execution(self, record: dict[str, Any]) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """INSERT INTO execution_records
                   (execution_record_id, parent_execution_record_id, trace_id, request_id, claimed_actor_id,
                     operator_id, identity_verification_id,
                     identity_context_digest, scenario, execution_path, state, handling_type, reason_code, versions_json,
                     data_reference, request_data_references_json, request_context_json, input_digest, result_json,
                     existing_system_reference_json, candidate_asset_reference_json,
                     sandbox_execution_reference_json, model_analysis_json, routing_decision_json,
                     validation_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["execution_record_id"], record["parent_execution_record_id"],
                    record["trace_id"], record["request_id"],
                    record["claimed_actor_id"], record["operator_id"],
                    record["identity_verification_id"], record["identity_context_digest"], record["business_type"],
                    record["execution_path"],
                    record["state"], record["handling_type"], record["reason_code"],
                    json.dumps(record["versions"]), record["data_reference"],
                    json.dumps(record["request_data_references"]), json.dumps(record["request_context"]),
                    record["input_digest"],
                    json.dumps(record["result"]), json.dumps(record["existing_system_reference"]),
                    json.dumps(record["candidate_asset_reference"]),
                    json.dumps(record["sandbox_execution_reference"]),
                    json.dumps(record["model_analysis"]),
                    json.dumps(record["routing_decision"]),
                    json.dumps(record["validation"]), record["created_at"],
                ),
            )

    def get_by_trace(self, trace_id: str) -> dict[str, Any] | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM execution_records WHERE trace_id = ? ORDER BY created_at DESC LIMIT 1", (trace_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_by_id(self, execution_record_id: str) -> dict[str, Any] | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM execution_records WHERE execution_record_id = ?", (execution_record_id,)
            ).fetchone()
        return dict(row) if row else None

    def has_human_handling(self, execution_record_id: str) -> bool:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT 1 FROM human_handling_records WHERE execution_record_id = ?", (execution_record_id,)
            ).fetchone()
        return row is not None

    def get_human_handling(self, execution_record_id: str) -> dict[str, Any] | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                """SELECT * FROM human_handling_records
                   WHERE execution_record_id = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (execution_record_id,),
            ).fetchone()
        return dict(row) if row else None

    def save_human_handling(self, record: dict[str, Any]) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """INSERT INTO human_handling_records
                   (handling_record_id, execution_record_id, trace_id, handler_id, identity_verification_id,
                    identity_context_digest, action, comment, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["handling_record_id"], record["execution_record_id"], record["trace_id"],
                    record["handler_id"], record["identity_verification_id"], record["identity_context_digest"],
                    record["action"], record["comment"], record["created_at"],
                ),
            )

    def update_execution_state(
        self, execution_record_id: str, state: str, handling_type: str, reason_code: str | None
    ) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """UPDATE execution_records SET state = ?, handling_type = ?, reason_code = ?
                   WHERE execution_record_id = ?""",
                (state, handling_type, reason_code, execution_record_id),
            )

    def get_idempotency(
        self, caller_service_code: str, action: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                """SELECT * FROM idempotency_records
                   WHERE caller_service_code = ? AND action = ? AND idempotency_key = ?""",
                (caller_service_code, action, idempotency_key),
            ).fetchone()
        return dict(row) if row else None

    def claim_idempotency(self, record: dict[str, Any]) -> bool:
        try:
            with connect(self.database_path) as connection:
                connection.execute(
                    """INSERT INTO idempotency_records
                       (caller_service_code, action, idempotency_key, request_digest, status,
                        trace_id, execution_record_id, reply_json, created_at, updated_at, expires_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record["caller_service_code"], record["action"], record["idempotency_key"],
                        record["request_digest"], record["status"], record["trace_id"],
                        record.get("execution_record_id"), None, record["created_at"],
                        record["updated_at"], record["expires_at"],
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def delete_idempotency(
        self, caller_service_code: str, action: str, idempotency_key: str
    ) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """DELETE FROM idempotency_records
                   WHERE caller_service_code = ? AND action = ? AND idempotency_key = ?""",
                (caller_service_code, action, idempotency_key),
            )

    def complete_idempotency(
        self,
        caller_service_code: str,
        action: str,
        idempotency_key: str,
        status: str,
        execution_record_id: str | None,
        reply: dict[str, Any],
        updated_at: str,
    ) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """UPDATE idempotency_records
                   SET status = ?, execution_record_id = ?, reply_json = ?, updated_at = ?
                   WHERE caller_service_code = ? AND action = ? AND idempotency_key = ?""",
                (
                    status, execution_record_id, json.dumps(reply, ensure_ascii=False), updated_at,
                    caller_service_code, action, idempotency_key,
                ),
            )

    @staticmethod
    def _insert_transition(
        connection: Any,
        rule_version_id: int,
        capability_code: str,
        from_status: str | None,
        to_status: str,
        action: str,
        actor_id: str,
        comment: str,
    ) -> None:
        connection.execute(
            """INSERT INTO rule_version_transition_records
               (transition_record_id, rule_version_id, capability_code, from_status, to_status,
                action, actor_id, comment, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"RVT-{uuid4().hex[:12].upper()}", rule_version_id, capability_code, from_status,
                to_status, action, actor_id, comment, datetime.now(timezone.utc).isoformat(),
            ),
        )
