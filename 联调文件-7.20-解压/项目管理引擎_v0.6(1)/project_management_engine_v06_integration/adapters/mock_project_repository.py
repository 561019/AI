from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from db import DEFAULT_DB_PATH, connect, init_db


def utc_now_text():
    # type: () -> str
    return datetime.now(timezone.utc).isoformat()


class MockProjectRepository:
    """
    SQLite 仅模拟数据操作引擎与 L1.7 的持久化链路。
    正式环境不应由项目管理引擎直连业务数据库。
    """

    def __init__(self, db_path=DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        init_db(self.db_path)

    # ---------------- 项目 ----------------

    def next_project_sequence(self, date_key):
        # type: (str) -> int
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT current_value FROM project_sequences WHERE date_key = ?",
                (date_key,),
            ).fetchone()
            if row is None:
                value = 1
                conn.execute(
                    "INSERT INTO project_sequences(date_key, current_value) VALUES (?, ?)",
                    (date_key, value),
                )
            else:
                value = int(row["current_value"]) + 1
                conn.execute(
                    "UPDATE project_sequences SET current_value = ? WHERE date_key = ?",
                    (value, date_key),
                )
            return value

    def create_project(self, project):
        # type: (Dict[str, Any]) -> None
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO projects(
                    project_id, project_name, project_category, project_grade,
                    budget_attribute, lifecycle_phase, business_status,
                    initiator_person_id, description, approval_workflow_id,
                    approval_basis_ref, created_at, activated_at, archived_at,
                    version, last_trace_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project["project_id"],
                    project["project_name"],
                    project["project_category"],
                    project["project_grade"],
                    project["budget_attribute"],
                    project["lifecycle_phase"],
                    project["business_status"],
                    project["initiator_person_id"],
                    project.get("description"),
                    project.get("approval_workflow_id"),
                    project.get("approval_basis_ref"),
                    project["created_at"],
                    project.get("activated_at"),
                    project.get("archived_at"),
                    project.get("version", 1),
                    project["last_trace_id"],
                ),
            )

    def get_project(self, project_id):
        # type: (str) -> Optional[Dict[str, Any]]
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_projects(self):
        # type: () -> List[Dict[str, Any]]
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def update_project_status(
        self,
        *,
        project_id,
        target_status,
        lifecycle_phase,
        trace_id,
        activated_at=None,
        archived_at=None,
        approval_basis_ref=None
    ):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE projects
                SET business_status = ?,
                    lifecycle_phase = ?,
                    last_trace_id = ?,
                    activated_at = COALESCE(?, activated_at),
                    archived_at = COALESCE(?, archived_at),
                    approval_basis_ref = COALESCE(?, approval_basis_ref),
                    version = version + 1
                WHERE project_id = ?
                """,
                (
                    target_status,
                    lifecycle_phase,
                    trace_id,
                    activated_at,
                    archived_at,
                    approval_basis_ref,
                    project_id,
                ),
            )

    def update_project_grade(self, *, project_id, target_grade, trace_id):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE projects
                SET project_grade = ?, last_trace_id = ?, version = version + 1
                WHERE project_id = ?
                """,
                (target_grade, trace_id, project_id),
            )

    def append_status_event(
        self,
        *,
        project_id,
        from_status,
        to_status,
        event_type,
        operator_person_id,
        trace_id,
        event_reason=None,
        basis_ref=None,
        workflow_instance_id=None
    ):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO project_status_events(
                    project_id, from_status, to_status, event_type,
                    event_reason, basis_ref, operator_person_id,
                    workflow_instance_id, trace_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    from_status,
                    to_status,
                    event_type,
                    event_reason,
                    basis_ref,
                    operator_person_id,
                    workflow_instance_id,
                    trace_id,
                    utc_now_text(),
                ),
            )

    def append_approval_record(
        self,
        *,
        project_id,
        approval_result,
        operator_person_id,
        trace_id,
        approval_basis_ref=None,
        workflow_instance_id=None
    ):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO approval_records(
                    project_id, approval_result, approval_basis_ref,
                    workflow_instance_id, operator_person_id, trace_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    approval_result,
                    approval_basis_ref,
                    workflow_instance_id,
                    operator_person_id,
                    trace_id,
                    utc_now_text(),
                ),
            )

    def get_status_events(self, project_id):
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM project_status_events WHERE project_id = ? ORDER BY event_id",
                (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_approval_records(self, project_id):
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM approval_records WHERE project_id = ? ORDER BY approval_record_id",
                (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---------------- 成员名册 ----------------

    def new_member_record_id(self):
        return "MEMBER_" + uuid4().hex[:16].upper()

    def get_active_member(self, project_id, person_id):
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM project_members
                WHERE project_id = ?
                  AND person_id = ?
                  AND membership_status = 'ACTIVE'
                ORDER BY joined_at DESC
                LIMIT 1
                """,
                (project_id, person_id),
            ).fetchone()
            return self._decode_member(dict(row)) if row else None

    def get_latest_member(self, project_id, person_id):
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM project_members
                WHERE project_id = ? AND person_id = ?
                ORDER BY joined_at DESC
                LIMIT 1
                """,
                (project_id, person_id),
            ).fetchone()
            return self._decode_member(dict(row)) if row else None

    def create_active_member(self, member):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO project_members(
                    member_record_id, project_id, person_id, person_name,
                    position_code, project_role, membership_status,
                    permission_scope_json, allowed_actions_json,
                    valid_from, valid_until, authorization_basis_ref,
                    joined_at, left_at, last_decision_id,
                    last_trace_id, version
                )
                VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?, ?, NULL, ?, ?, 1)
                """,
                (
                    member["member_record_id"],
                    member["project_id"],
                    member["person_id"],
                    member["person_name"],
                    member["position_code"],
                    member["project_role"],
                    json.dumps(member["permission_scope"], ensure_ascii=False),
                    json.dumps(member["allowed_actions"], ensure_ascii=False),
                    member.get("valid_from"),
                    member.get("valid_until"),
                    member.get("authorization_basis_ref"),
                    member["joined_at"],
                    member.get("last_decision_id"),
                    member["last_trace_id"],
                ),
            )

    def exit_member(self, *, member_record_id, left_at, decision_id, trace_id):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE project_members
                SET membership_status = 'EXITED',
                    left_at = ?,
                    last_decision_id = ?,
                    last_trace_id = ?,
                    version = version + 1
                WHERE member_record_id = ?
                  AND membership_status = 'ACTIVE'
                """,
                (left_at, decision_id, trace_id, member_record_id),
            )

    def supersede_member(self, *, member_record_id, ended_at, decision_id, trace_id):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE project_members
                SET membership_status = 'SUPERSEDED',
                    left_at = ?,
                    last_decision_id = ?,
                    last_trace_id = ?,
                    version = version + 1
                WHERE member_record_id = ? AND membership_status = 'ACTIVE'
                """,
                (ended_at, decision_id, trace_id, member_record_id),
            )

    def list_members(self, project_id, include_exited=False):
        query = """
            SELECT *
            FROM project_members
            WHERE project_id = ?
        """
        params = [project_id]
        if not include_exited:
            query += " AND membership_status = 'ACTIVE'"
        query += " ORDER BY joined_at, person_id"

        with connect(self.db_path) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [self._decode_member(dict(row)) for row in rows]

    @staticmethod
    def _decode_member(row):
        row["permission_scope"] = json.loads(row.pop("permission_scope_json"))
        row["allowed_actions"] = json.loads(row.pop("allowed_actions_json"))
        return row

    def append_member_event(
        self,
        *,
        member_record_id,
        project_id,
        person_id,
        event_type,
        event_result,
        operator_person_id,
        trace_id,
        project_role=None,
        position_code=None,
        decision_id=None,
        reason=None
    ):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO project_member_events(
                    member_record_id, project_id, person_id,
                    event_type, event_result, project_role,
                    position_code, decision_id, reason,
                    operator_person_id, trace_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    member_record_id,
                    project_id,
                    person_id,
                    event_type,
                    event_result,
                    project_role,
                    position_code,
                    decision_id,
                    reason,
                    operator_person_id,
                    trace_id,
                    utc_now_text(),
                ),
            )

    def append_permission_record(
        self,
        *,
        member_record_id,
        project_id,
        person_id,
        permission_action,
        requested_scope,
        allowed_actions,
        decision_id,
        decision_result,
        operator_person_id,
        trace_id,
        valid_from=None,
        valid_until=None,
        basis_ref=None,
        decision_reason=None
    ):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO project_permission_records(
                    member_record_id, project_id, person_id,
                    permission_action, requested_scope_json,
                    allowed_actions_json, valid_from, valid_until,
                    basis_ref, decision_id, decision_result,
                    decision_reason, operator_person_id,
                    trace_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    member_record_id,
                    project_id,
                    person_id,
                    permission_action,
                    json.dumps(requested_scope, ensure_ascii=False),
                    json.dumps(allowed_actions, ensure_ascii=False),
                    valid_from,
                    valid_until,
                    basis_ref,
                    decision_id,
                    decision_result,
                    decision_reason,
                    operator_person_id,
                    trace_id,
                    utc_now_text(),
                ),
            )

    def get_member_events(self, project_id):
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM project_member_events
                WHERE project_id = ?
                ORDER BY event_id
                """,
                (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_permission_records(self, project_id):
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM project_permission_records
                WHERE project_id = ?
                ORDER BY permission_record_id
                """,
                (project_id,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["requested_scope"] = json.loads(
                    item.pop("requested_scope_json")
                )
                item["allowed_actions"] = json.loads(
                    item.pop("allowed_actions_json")
                )
                result.append(item)
            return result


    # ---------------- 项目收尾与归档 ----------------

    def new_closure_record_id(self):
        return "CLOSURE_" + uuid4().hex[:16].upper()

    def create_closure_record(self, record):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO project_closure_records(
                    closure_record_id, project_id, closure_status,
                    closure_basis_ref, revocation_status, archive_status,
                    active_member_count, revoked_member_count,
                    failed_member_count, archive_catalog_ref,
                    failure_reason, operator_person_id,
                    workflow_instance_id, trace_id,
                    created_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["closure_record_id"],
                    record["project_id"],
                    record["closure_status"],
                    record["closure_basis_ref"],
                    record["revocation_status"],
                    record["archive_status"],
                    record["active_member_count"],
                    record["revoked_member_count"],
                    record["failed_member_count"],
                    record.get("archive_catalog_ref"),
                    record.get("failure_reason"),
                    record["operator_person_id"],
                    record.get("workflow_instance_id"),
                    record["trace_id"],
                    record["created_at"],
                    record.get("completed_at"),
                ),
            )

    def append_bulk_revocation_item(self, item):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO project_bulk_revocation_items(
                    closure_record_id, project_id, member_record_id,
                    person_id, decision_id, decision_result,
                    decision_reason, trace_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["closure_record_id"],
                    item["project_id"],
                    item["member_record_id"],
                    item["person_id"],
                    item["decision_id"],
                    item["decision_result"],
                    item.get("decision_reason"),
                    item["trace_id"],
                    item["created_at"],
                ),
            )

    def append_archive_catalog_item(self, item):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO project_archive_catalog(
                    catalog_item_id, closure_record_id, project_id,
                    resource_type, resource_name, data_ref,
                    artifact_ref, asset_ref, version,
                    data_labels_json, archive_status,
                    sealed_at, trace_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["catalog_item_id"],
                    item["closure_record_id"],
                    item["project_id"],
                    item["resource_type"],
                    item["resource_name"],
                    item.get("data_ref"),
                    item.get("artifact_ref"),
                    item.get("asset_ref"),
                    item.get("version"),
                    json.dumps(item.get("data_labels", []), ensure_ascii=False),
                    item["archive_status"],
                    item.get("sealed_at"),
                    item["trace_id"],
                    item["created_at"],
                ),
            )

    def get_closure_records(self, project_id):
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM project_closure_records
                WHERE project_id = ?
                ORDER BY created_at, closure_record_id
                """,
                (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_bulk_revocation_items(self, project_id):
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM project_bulk_revocation_items
                WHERE project_id = ?
                ORDER BY item_id
                """,
                (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_archive_catalog(self, project_id):
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM project_archive_catalog
                WHERE project_id = ?
                ORDER BY created_at, catalog_item_id
                """,
                (project_id,),
            ).fetchall()

            result = []
            for row in rows:
                item = dict(row)
                item["data_labels"] = json.loads(
                    item.pop("data_labels_json")
                )
                result.append(item)
            return result


    # ---------------- 封存项目重新授权 ----------------

    def new_access_authorization_id(self):
        return "ARCHAUTH_" + uuid4().hex[:16].upper()

    def append_access_authorization(self, record):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO project_access_authorizations(
                    authorization_record_id,
                    project_id,
                    applicant_person_id,
                    applicant_name,
                    allowed_actions_json,
                    allowed_scope_json,
                    authorization_basis_ref,
                    decision_id,
                    decision_result,
                    decision_reason,
                    valid_from,
                    valid_until,
                    operator_person_id,
                    trace_id,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["authorization_record_id"],
                    record["project_id"],
                    record["applicant_person_id"],
                    record["applicant_name"],
                    json.dumps(
                        record["allowed_actions"],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        record["allowed_scope"],
                        ensure_ascii=False,
                    ),
                    record["authorization_basis_ref"],
                    record["decision_id"],
                    record["decision_result"],
                    record.get("decision_reason"),
                    record["valid_from"],
                    record["valid_until"],
                    record["operator_person_id"],
                    record["trace_id"],
                    record["created_at"],
                ),
            )

    def list_access_authorizations(
        self,
        project_id,
        applicant_person_id=None
    ):
        query = """
            SELECT *
            FROM project_access_authorizations
            WHERE project_id = ?
        """
        params = [project_id]

        if applicant_person_id:
            query += " AND applicant_person_id = ?"
            params.append(applicant_person_id)

        query += " ORDER BY created_at DESC, authorization_record_id DESC"

        with connect(self.db_path) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        result = []
        for row in rows:
            item = dict(row)
            item["allowed_actions"] = json.loads(
                item.pop("allowed_actions_json")
            )
            item["allowed_scope"] = json.loads(
                item.pop("allowed_scope_json")
            )
            result.append(item)
        return result

    # ---------------- 档位转换 ----------------

    def new_grade_change_record_id(self):
        return "GRADECHANGE_" + uuid4().hex[:16].upper()

    def append_grade_change_record(self, record):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO project_grade_change_records(
                    grade_change_record_id, project_id, from_grade,
                    target_grade, change_result, change_basis_ref,
                    change_reason, workflow_instance_id, task_id,
                    operator_person_id, trace_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["grade_change_record_id"], record["project_id"],
                    record["from_grade"], record["target_grade"],
                    record["change_result"], record["change_basis_ref"],
                    record.get("change_reason"), record.get("workflow_instance_id"),
                    record.get("task_id"), record["operator_person_id"],
                    record["trace_id"], record["created_at"],
                ),
            )

    def get_grade_change_records(self, project_id):
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM project_grade_change_records WHERE project_id = ? ORDER BY created_at, grade_change_record_id",
                (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    # ---------------- 动作级权限与安全审计 ----------------

    def append_action_decision(self, record):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO project_action_decisions(
                    project_id, actor_person_id, action, resource_scope_json,
                    decision_id, permission_result, permission_reason,
                    audit_ref, security_result, security_reason, trace_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.get("project_id"), record["actor_person_id"], record["action"],
                    json.dumps(record.get("resource_scope", {}), ensure_ascii=False),
                    record["decision_id"], record["permission_result"], record.get("permission_reason"),
                    record["audit_ref"], record["security_result"], record.get("security_reason"),
                    record["trace_id"], utc_now_text(),
                ),
            )

    def get_action_decisions(self, project_id=None, trace_id=None):
        query = "SELECT * FROM project_action_decisions WHERE 1=1"
        params = []
        if project_id is not None:
            query += " AND project_id = ?"
            params.append(project_id)
        if trace_id is not None:
            query += " AND trace_id = ?"
            params.append(trace_id)
        query += " ORDER BY action_decision_record_id"
        with connect(self.db_path) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["resource_scope"] = json.loads(item.pop("resource_scope_json"))
            result.append(item)
        return result

    # ---------------- 异步任务与回调 ----------------

    def create_async_task(self, task):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO project_async_tasks(
                    task_id, action, project_id, workflow_instance_id, node_id,
                    task_status, progress_percent, status_message,
                    request_payload_json, final_result_json, source_message_id,
                    idempotency_key, trace_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    task["task_id"], task["action"], task.get("project_id"),
                    task.get("workflow_instance_id"), task.get("node_id"),
                    task["task_status"], task["progress_percent"], task.get("status_message"),
                    json.dumps(task.get("request_payload", {}), ensure_ascii=False),
                    task.get("source_message_id"), task["idempotency_key"],
                    task["trace_id"], task["created_at"], task["updated_at"],
                ),
            )

    def get_async_task(self, task_id):
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM project_async_tasks WHERE task_id = ?", (task_id,)).fetchone()
        return self._decode_task(dict(row)) if row else None

    def get_async_task_by_idempotency(self, idempotency_key):
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM project_async_tasks WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        return self._decode_task(dict(row)) if row else None

    @staticmethod
    def _decode_task(item):
        item["request_payload"] = json.loads(item.pop("request_payload_json"))
        raw = item.pop("final_result_json")
        item["final_result"] = json.loads(raw) if raw else None
        return item

    def update_async_task(self, *, task_id, task_status, progress_percent, status_message=None, final_result=None):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE project_async_tasks
                SET task_status = ?, progress_percent = ?, status_message = ?,
                    final_result_json = COALESCE(?, final_result_json), updated_at = ?
                WHERE task_id = ?
                """,
                (
                    task_status, progress_percent, status_message,
                    json.dumps(final_result, ensure_ascii=False) if final_result is not None else None,
                    utc_now_text(), task_id,
                ),
            )

    def list_async_tasks(self, project_id=None):
        query = "SELECT * FROM project_async_tasks"
        params = []
        if project_id is not None:
            query += " WHERE project_id = ?"
            params.append(project_id)
        query += " ORDER BY created_at DESC"
        with connect(self.db_path) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._decode_task(dict(row)) for row in rows]

    def append_workflow_callback(self, record):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO workflow_callback_records(
                    task_id, callback_type, callback_status, progress_percent,
                    result_json, message_id, parent_message_id, trace_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["task_id"], record["callback_type"], record["callback_status"],
                    record.get("progress_percent"),
                    json.dumps(record.get("result"), ensure_ascii=False) if record.get("result") is not None else None,
                    record.get("message_id"), record.get("parent_message_id"),
                    record["trace_id"], utc_now_text(),
                ),
            )

    def get_workflow_callbacks(self, task_id):
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_callback_records WHERE task_id = ? ORDER BY callback_record_id",
                (task_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            raw = item.pop("result_json")
            item["result"] = json.loads(raw) if raw else None
            result.append(item)
        return result

    # ---------------- 消息接收留痕 ----------------

    def register_message_receipt(self, record):
        try:
            with connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO message_receipts(
                        message_id, parent_message_id, trace_id,
                        source_service_code, route_type, action, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["message_id"], record.get("parent_message_id"), record["trace_id"],
                        record["source_service_code"], record["route_type"], record["action"], utc_now_text(),
                    ),
                )
            return True
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                return False
            raise

    # ---------------- 幂等 ----------------

    def get_idempotency(self, idempotency_key):
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM idempotency_records WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            return dict(row) if row else None

    def save_idempotency(
        self,
        *,
        idempotency_key,
        action,
        request_hash,
        reply
    ):
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO idempotency_records(
                    idempotency_key, action, request_hash,
                    reply_json, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    action,
                    request_hash,
                    json.dumps(reply, ensure_ascii=False),
                    utc_now_text(),
                ),
            )
