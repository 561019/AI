import sqlite3

from adapters.mock_data_module import (
    DB_PATH,
    get_connection,
)


def get_conn():
    return get_connection()


def _column_exists(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return any(row["name"] == column_name for row in cur.fetchall())


def _ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    if not _column_exists(conn, table_name, column_name):
        conn.execute(
            f"ALTER TABLE {table_name} "
            f"ADD COLUMN {column_name} {column_type}"
        )


def _ensure_append_only_triggers(
    conn: sqlite3.Connection,
) -> None:
    """
    五类闭环业务记录采用只增不改策略。
    通过数据库触发器阻止 UPDATE / DELETE，避免业务代码误改历史事实。
    """
    tables = (
        "reminder_record",
        "delivery_record",
        "confirm_record",
        "escalation_record",
        "recovery_record",
    )

    for table_name in tables:
        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_update
            BEFORE UPDATE ON {table_name}
            BEGIN
                SELECT RAISE(
                    ABORT,
                    '{table_name} is append-only: UPDATE is forbidden'
                );
            END
            """
        )
        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_delete
            BEFORE DELETE ON {table_name}
            BEGIN
                SELECT RAISE(
                    ABORT,
                    '{table_name} is append-only: DELETE is forbidden'
                );
            END
            """
        )


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS monitor_item (
        item_id TEXT PRIMARY KEY,
        trace_id TEXT,
        object_type TEXT,
        object_id TEXT,
        rule_id TEXT,
        trigger_time TEXT,
        rule_version TEXT,
        receiver_role TEXT,
        delivery_channel TEXT,
        notice_type TEXT,
        alert_level TEXT,
        dedup_key TEXT,
        repeat_interval INTEGER,
        merge_key TEXT,
        merge_window INTEGER,
        dnd_rule_ref TEXT,
        escalation_rule_ref TEXT,
        template_id TEXT,
        template_version TEXT,
        status TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    # 兼容旧数据库：已有表不会因 CREATE TABLE 自动增加新列。
    _ensure_column(conn, "monitor_item", "updated_at", "TEXT")
    _ensure_column(conn, "monitor_item", "template_id", "TEXT")
    _ensure_column(conn, "monitor_item", "template_version", "TEXT")
    _ensure_column(conn, "monitor_item", "merge_key", "TEXT")
    _ensure_column(conn, "monitor_item", "merge_window", "INTEGER")
    _ensure_column(conn, "monitor_item", "dnd_rule_ref", "TEXT")
    _ensure_column(conn, "monitor_item", "escalation_rule_ref", "TEXT")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reminder_record (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trace_id TEXT,
        item_id TEXT,
        reason TEXT,
        content TEXT,
        status TEXT,
        template_id TEXT,
        template_version TEXT,
        alert_level TEXT,
        trigger_value TEXT,
        event_id TEXT,
        governance_action TEXT,
        governance_reason TEXT,
        merged_into_reminder_id INTEGER,
        dnd_rule_ref TEXT,
        escalation_rule_ref TEXT,
        next_eligible_at TEXT,
        created_at TEXT
    )
    """)
    _ensure_column(conn, "reminder_record", "template_id", "TEXT")
    _ensure_column(conn, "reminder_record", "template_version", "TEXT")
    _ensure_column(conn, "reminder_record", "alert_level", "TEXT")
    _ensure_column(conn, "reminder_record", "trigger_value", "TEXT")
    _ensure_column(conn, "reminder_record", "event_id", "TEXT")
    _ensure_column(conn, "reminder_record", "governance_action", "TEXT")
    _ensure_column(conn, "reminder_record", "governance_reason", "TEXT")
    _ensure_column(conn, "reminder_record", "merged_into_reminder_id", "INTEGER")
    _ensure_column(conn, "reminder_record", "dnd_rule_ref", "TEXT")
    _ensure_column(conn, "reminder_record", "escalation_rule_ref", "TEXT")
    _ensure_column(conn, "reminder_record", "next_eligible_at", "TEXT")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS delivery_record (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reminder_id INTEGER,
        trace_id TEXT,
        item_id TEXT,
        receiver_role TEXT,
        receiver_user TEXT,
        delivery_status TEXT,
        reason TEXT,
        created_at TEXT
    )
    """)
    _ensure_column(conn, "delivery_record", "reminder_id", "INTEGER")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS confirm_record (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reminder_id INTEGER,
        trace_id TEXT,
        item_id TEXT,
        confirm_user TEXT,
        confirm_status TEXT,
        created_at TEXT
    )
    """)
    _ensure_column(conn, "confirm_record", "reminder_id", "INTEGER")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS escalation_record (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reminder_id INTEGER,
        trace_id TEXT,
        item_id TEXT,
        escalation_role TEXT,
        reason TEXT,
        created_at TEXT
    )
    """)
    _ensure_column(conn, "escalation_record", "reminder_id", "INTEGER")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS recovery_record (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reminder_id INTEGER,
        trace_id TEXT,
        item_id TEXT,
        recovery_status TEXT,
        created_at TEXT
    )
    """)
    _ensure_column(conn, "recovery_record", "reminder_id", "INTEGER")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS layer_idempotency_record (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        idempotency_key TEXT UNIQUE NOT NULL,
        request_hash TEXT NOT NULL,
        message_id TEXT,
        trace_id TEXT,
        action TEXT,
        status TEXT,
        response_code INTEGER,
        response_json TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS api_request_record (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT,
        trace_id TEXT,
        source_module TEXT,
        operator_id TEXT,
        request_method TEXT,
        request_path TEXT,
        response_code INTEGER,
        business_status TEXT,
        error_message TEXT,
        permission_name TEXT,
        permission_mode TEXT,
        permission_allowed INTEGER,
        permission_decision_id TEXT,
        security_audit_ref TEXT,
        duration_ms INTEGER,
        client_ip TEXT,
        created_at TEXT
    )
    """)

    # 兼容 v0.5 及更早数据库：自动补齐权限审计字段。
    _ensure_column(conn, "api_request_record", "permission_name", "TEXT")
    _ensure_column(conn, "api_request_record", "permission_mode", "TEXT")
    _ensure_column(conn, "api_request_record", "permission_allowed", "INTEGER")
    _ensure_column(conn, "api_request_record", "permission_decision_id", "TEXT")
    _ensure_column(conn, "api_request_record", "security_audit_ref", "TEXT")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS workflow_callback_record (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        callback_id TEXT UNIQUE,
        trace_id TEXT,
        workflow_instance_id TEXT,
        node_id TEXT,
        task_id TEXT,
        reply_type TEXT,
        status TEXT,
        result_ref TEXT,
        error_code TEXT,
        created_at TEXT
    )
    """)

    _ensure_append_only_triggers(conn)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_monitor_item_trace
    ON monitor_item(trace_id)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_layer_idempotency_trace
    ON layer_idempotency_record(trace_id)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_layer_idempotency_message
    ON layer_idempotency_record(message_id)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_api_request_id
    ON api_request_record(request_id)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_api_trace_id
    ON api_request_record(trace_id)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_api_created_at
    ON api_request_record(created_at)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_delivery_reminder
    ON delivery_record(reminder_id)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_confirm_reminder
    ON confirm_record(reminder_id)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_escalation_reminder
    ON escalation_record(reminder_id)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_recovery_reminder
    ON recovery_record(reminder_id)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_monitor_merge_key
    ON monitor_item(merge_key)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_reminder_event_id
    ON reminder_record(event_id)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_reminder_governance_action
    ON reminder_record(governance_action)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_reminder_merged_into
    ON reminder_record(merged_into_reminder_id)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_workflow_callback_trace
    ON workflow_callback_record(trace_id)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_workflow_callback_task
    ON workflow_callback_record(task_id)
    """)

    conn.commit()
    conn.close()
