from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ROOT_DIR / "data" / "l1_6.sqlite3"
SCHEMA_PATH = ROOT_DIR / "schema.sql"


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns that may be missing from older databases."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversation_message (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          project_id TEXT NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          token_estimate INTEGER NOT NULL DEFAULT 0,
          model_provider TEXT,
          model_name TEXT,
          trace_id TEXT,
          created_by TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(session_id) REFERENCES conversation_session(id),
          FOREIGN KEY(trace_id) REFERENCES prompt_run_trace(id)
        );

        CREATE INDEX IF NOT EXISTS idx_conversation_message_session
          ON conversation_message(session_id, created_at);

        CREATE TABLE IF NOT EXISTS handoff_run (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL,
          old_session_id TEXT NOT NULL,
          new_session_id TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'started',
          user_message_id TEXT,
          assistant_message_id TEXT,
          trace_id TEXT,
          work_report_id TEXT,
          handoff_file_id TEXT,
          sync_package_id TEXT,
          user_text TEXT NOT NULL,
          assistant_text TEXT,
          llm_meta TEXT,
          created_by TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_handoff_run_old_session
          ON handoff_run(old_session_id, created_at);

        CREATE TABLE IF NOT EXISTS cross_project_reference (
          id TEXT PRIMARY KEY,
          target_project_id TEXT NOT NULL,
          source_project_id TEXT NOT NULL,
          source_session_id TEXT,
          source_record_type TEXT NOT NULL,
          source_record_id TEXT NOT NULL,
          source_name TEXT NOT NULL,
          source_excerpt TEXT NOT NULL,
          note TEXT,
          status TEXT NOT NULL DEFAULT 'active',
          created_by TEXT NOT NULL,
          created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cross_project_reference_target
          ON cross_project_reference(target_project_id, status, created_at);

        CREATE TABLE IF NOT EXISTS control_center_message (
          id TEXT PRIMARY KEY,
          scope_level TEXT NOT NULL,
          scope_id TEXT NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          meta TEXT,
          result_json TEXT,
          status TEXT NOT NULL DEFAULT 'active',
          created_by TEXT NOT NULL,
          created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_control_center_message_scope
          ON control_center_message(scope_level, scope_id, status, created_at);
        """
    )
    migrations = [
        ("auto_handoff_done", "INTEGER NOT NULL DEFAULT 0"),
        ("locked", "INTEGER NOT NULL DEFAULT 0"),
        ("next_session_id", "TEXT"),
    ]
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info('conversation_session')").fetchall()
    }
    for col_name, col_def in migrations:
        if col_name not in existing:
            conn.execute(
                f"ALTER TABLE conversation_session ADD COLUMN {col_name} {col_def}"
            )
    _migrate_columns(
        conn,
        "sync_package",
        [
            ("package_type", "TEXT NOT NULL DEFAULT 'project_master'"),
            ("structured_json", "TEXT"),
            ("session_index", "TEXT"),
            ("file_index", "TEXT"),
            ("topic_index", "TEXT"),
            ("pending_tasks", "TEXT"),
            ("next_actions", "TEXT"),
        ],
    )
    conn.execute("DROP INDEX IF EXISTS idx_sync_package_project_version")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sync_package_project_type_version
          ON sync_package(project_id, package_type, version_no)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sync_package_project_type
          ON sync_package(project_id, package_type, created_at)
        """
    )


def _migrate_columns(
    conn: sqlite3.Connection, table_name: str, columns: list[tuple[str, str]]
) -> None:
    existing = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    }
    for col_name, col_def in columns:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(row) for row in rows if row is not None]
