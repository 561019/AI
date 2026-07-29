from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "project_management.db"
PathLike = Union[str, Path]


def connect(db_path=DEFAULT_DB_PATH):
    # type: (PathLike) -> sqlite3.Connection
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=DEFAULT_DB_PATH):
    # type: (PathLike) -> None
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS project_sequences (
                date_key TEXT PRIMARY KEY,
                current_value INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                project_category TEXT NOT NULL,
                project_grade TEXT NOT NULL,
                budget_attribute TEXT NOT NULL,
                lifecycle_phase TEXT NOT NULL,
                business_status TEXT NOT NULL,
                initiator_person_id TEXT NOT NULL,
                description TEXT,
                approval_workflow_id TEXT,
                approval_basis_ref TEXT,
                created_at TEXT NOT NULL,
                activated_at TEXT,
                archived_at TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                last_trace_id TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_status_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_reason TEXT,
                basis_ref TEXT,
                operator_person_id TEXT NOT NULL,
                workflow_instance_id TEXT,
                trace_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS approval_records (
                approval_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                approval_result TEXT NOT NULL,
                approval_basis_ref TEXT,
                workflow_instance_id TEXT,
                operator_person_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS project_members (
                member_record_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                person_id TEXT NOT NULL,
                person_name TEXT NOT NULL,
                position_code TEXT NOT NULL,
                project_role TEXT NOT NULL,
                membership_status TEXT NOT NULL,
                permission_scope_json TEXT NOT NULL,
                allowed_actions_json TEXT NOT NULL,
                valid_from TEXT,
                valid_until TEXT,
                authorization_basis_ref TEXT,
                joined_at TEXT NOT NULL,
                left_at TEXT,
                last_decision_id TEXT,
                last_trace_id TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(project_id) REFERENCES projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS project_member_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_record_id TEXT,
                project_id TEXT NOT NULL,
                person_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_result TEXT NOT NULL,
                project_role TEXT,
                position_code TEXT,
                decision_id TEXT,
                reason TEXT,
                operator_person_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS project_permission_records (
                permission_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_record_id TEXT,
                project_id TEXT NOT NULL,
                person_id TEXT NOT NULL,
                permission_action TEXT NOT NULL,
                requested_scope_json TEXT NOT NULL,
                allowed_actions_json TEXT NOT NULL,
                valid_from TEXT,
                valid_until TEXT,
                basis_ref TEXT,
                decision_id TEXT NOT NULL,
                decision_result TEXT NOT NULL,
                decision_reason TEXT,
                operator_person_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS project_closure_records (
                closure_record_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                closure_status TEXT NOT NULL,
                closure_basis_ref TEXT NOT NULL,
                revocation_status TEXT NOT NULL,
                archive_status TEXT NOT NULL,
                active_member_count INTEGER NOT NULL DEFAULT 0,
                revoked_member_count INTEGER NOT NULL DEFAULT 0,
                failed_member_count INTEGER NOT NULL DEFAULT 0,
                archive_catalog_ref TEXT,
                failure_reason TEXT,
                operator_person_id TEXT NOT NULL,
                workflow_instance_id TEXT,
                trace_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS project_bulk_revocation_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                closure_record_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                member_record_id TEXT NOT NULL,
                person_id TEXT NOT NULL,
                decision_id TEXT NOT NULL,
                decision_result TEXT NOT NULL,
                decision_reason TEXT,
                trace_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(project_id),
                FOREIGN KEY(closure_record_id) REFERENCES project_closure_records(closure_record_id)
            );

            CREATE TABLE IF NOT EXISTS project_archive_catalog (
                catalog_item_id TEXT PRIMARY KEY,
                closure_record_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_name TEXT NOT NULL,
                data_ref TEXT,
                artifact_ref TEXT,
                asset_ref TEXT,
                version TEXT,
                data_labels_json TEXT NOT NULL,
                archive_status TEXT NOT NULL,
                sealed_at TEXT,
                trace_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(project_id),
                FOREIGN KEY(closure_record_id) REFERENCES project_closure_records(closure_record_id)
            );

            CREATE TABLE IF NOT EXISTS project_access_authorizations (
                authorization_record_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                applicant_person_id TEXT NOT NULL,
                applicant_name TEXT NOT NULL,
                allowed_actions_json TEXT NOT NULL,
                allowed_scope_json TEXT NOT NULL,
                authorization_basis_ref TEXT NOT NULL,
                decision_id TEXT NOT NULL,
                decision_result TEXT NOT NULL,
                decision_reason TEXT,
                valid_from TEXT NOT NULL,
                valid_until TEXT NOT NULL,
                operator_person_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS project_grade_change_records (
                grade_change_record_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                from_grade TEXT NOT NULL,
                target_grade TEXT NOT NULL,
                change_result TEXT NOT NULL,
                change_basis_ref TEXT NOT NULL,
                change_reason TEXT,
                workflow_instance_id TEXT,
                task_id TEXT,
                operator_person_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS project_action_decisions (
                action_decision_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT,
                actor_person_id TEXT NOT NULL,
                action TEXT NOT NULL,
                resource_scope_json TEXT NOT NULL,
                decision_id TEXT NOT NULL,
                permission_result TEXT NOT NULL,
                permission_reason TEXT,
                audit_ref TEXT NOT NULL,
                security_result TEXT NOT NULL,
                security_reason TEXT,
                trace_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_async_tasks (
                task_id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                project_id TEXT,
                workflow_instance_id TEXT,
                node_id TEXT,
                task_status TEXT NOT NULL,
                progress_percent INTEGER NOT NULL,
                status_message TEXT,
                request_payload_json TEXT NOT NULL,
                final_result_json TEXT,
                source_message_id TEXT,
                idempotency_key TEXT NOT NULL UNIQUE,
                trace_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS workflow_callback_records (
                callback_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                callback_type TEXT NOT NULL,
                callback_status TEXT NOT NULL,
                progress_percent INTEGER,
                result_json TEXT,
                message_id TEXT,
                parent_message_id TEXT,
                trace_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES project_async_tasks(task_id)
            );

            CREATE TABLE IF NOT EXISTS message_receipts (
                message_id TEXT PRIMARY KEY,
                parent_message_id TEXT,
                trace_id TEXT NOT NULL,
                source_service_code TEXT NOT NULL,
                route_type TEXT NOT NULL,
                action TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS idempotency_records (
                idempotency_key TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                reply_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_projects_status
            ON projects(business_status);

            CREATE INDEX IF NOT EXISTS idx_members_project
            ON project_members(project_id, membership_status);

            CREATE INDEX IF NOT EXISTS idx_closure_project
            ON project_closure_records(project_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_archive_project
            ON project_archive_catalog(project_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_archive_authorization_project_person
            ON project_access_authorizations(
                project_id,
                applicant_person_id,
                created_at
            );

            CREATE INDEX IF NOT EXISTS idx_grade_change_project
            ON project_grade_change_records(project_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_action_decision_project
            ON project_action_decisions(project_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_async_task_project
            ON project_async_tasks(project_id, created_at);

            CREATE UNIQUE INDEX IF NOT EXISTS idx_active_member_unique
            ON project_members(project_id, person_id)
            WHERE membership_status = 'ACTIVE';

            CREATE TRIGGER IF NOT EXISTS trg_project_status_events_no_update
            BEFORE UPDATE ON project_status_events
            BEGIN
                SELECT RAISE(ABORT, 'project_status_events is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_project_status_events_no_delete
            BEFORE DELETE ON project_status_events
            BEGIN
                SELECT RAISE(ABORT, 'project_status_events is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_approval_records_no_update
            BEFORE UPDATE ON approval_records
            BEGIN
                SELECT RAISE(ABORT, 'approval_records is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_approval_records_no_delete
            BEFORE DELETE ON approval_records
            BEGIN
                SELECT RAISE(ABORT, 'approval_records is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_project_member_events_no_update
            BEFORE UPDATE ON project_member_events
            BEGIN
                SELECT RAISE(ABORT, 'project_member_events is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_project_member_events_no_delete
            BEFORE DELETE ON project_member_events
            BEGIN
                SELECT RAISE(ABORT, 'project_member_events is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_project_permission_records_no_update
            BEFORE UPDATE ON project_permission_records
            BEGIN
                SELECT RAISE(ABORT, 'project_permission_records is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_project_permission_records_no_delete
            BEFORE DELETE ON project_permission_records
            BEGIN
                SELECT RAISE(ABORT, 'project_permission_records is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_project_closure_records_no_update
            BEFORE UPDATE ON project_closure_records
            BEGIN
                SELECT RAISE(ABORT, 'project_closure_records is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_project_closure_records_no_delete
            BEFORE DELETE ON project_closure_records
            BEGIN
                SELECT RAISE(ABORT, 'project_closure_records is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_bulk_revocation_no_update
            BEFORE UPDATE ON project_bulk_revocation_items
            BEGIN
                SELECT RAISE(ABORT, 'project_bulk_revocation_items is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_bulk_revocation_no_delete
            BEFORE DELETE ON project_bulk_revocation_items
            BEGIN
                SELECT RAISE(ABORT, 'project_bulk_revocation_items is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_grade_change_no_update
            BEFORE UPDATE ON project_grade_change_records
            BEGIN SELECT RAISE(ABORT, 'project_grade_change_records is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS trg_grade_change_no_delete
            BEFORE DELETE ON project_grade_change_records
            BEGIN SELECT RAISE(ABORT, 'project_grade_change_records is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS trg_action_decisions_no_update
            BEFORE UPDATE ON project_action_decisions
            BEGIN SELECT RAISE(ABORT, 'project_action_decisions is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS trg_action_decisions_no_delete
            BEFORE DELETE ON project_action_decisions
            BEGIN SELECT RAISE(ABORT, 'project_action_decisions is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS trg_callbacks_no_update
            BEFORE UPDATE ON workflow_callback_records
            BEGIN SELECT RAISE(ABORT, 'workflow_callback_records is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS trg_callbacks_no_delete
            BEFORE DELETE ON workflow_callback_records
            BEGIN SELECT RAISE(ABORT, 'workflow_callback_records is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS trg_message_receipts_no_update
            BEFORE UPDATE ON message_receipts
            BEGIN SELECT RAISE(ABORT, 'message_receipts is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS trg_message_receipts_no_delete
            BEFORE DELETE ON message_receipts
            BEGIN SELECT RAISE(ABORT, 'message_receipts is append-only'); END;

            CREATE TRIGGER IF NOT EXISTS trg_access_authorizations_no_update
            BEFORE UPDATE ON project_access_authorizations
            BEGIN
                SELECT RAISE(ABORT, 'project_access_authorizations is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_access_authorizations_no_delete
            BEFORE DELETE ON project_access_authorizations
            BEGIN
                SELECT RAISE(ABORT, 'project_access_authorizations is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_archive_catalog_no_update
            BEFORE UPDATE ON project_archive_catalog
            BEGIN
                SELECT RAISE(ABORT, 'project_archive_catalog is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_archive_catalog_no_delete
            BEFORE DELETE ON project_archive_catalog
            BEGIN
                SELECT RAISE(ABORT, 'project_archive_catalog is append-only');
            END;
            """
        )
