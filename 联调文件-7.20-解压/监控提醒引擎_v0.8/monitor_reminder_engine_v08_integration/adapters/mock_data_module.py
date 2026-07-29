from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from adapters.adapter_registry import record_adapter_call


DB_PATH = Path("monitor_demo.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    record_adapter_call(
        "data_module_1_7",
        "data.connection.open",
        {
            "storage_class": "local_mock_sqlite",
            "data_ref": str(DB_PATH),
        },
    )
    return conn


def database_exists() -> bool:
    exists = DB_PATH.exists()
    record_adapter_call(
        "data_module_1_7",
        "data.health.exists",
        {"exists": exists, "data_ref": str(DB_PATH)},
    )
    return exists


def database_connected() -> bool:
    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        conn.close()
        connected = True
    except sqlite3.Error:
        connected = False

    record_adapter_call(
        "data_module_1_7",
        "data.health.connected",
        {"connected": connected, "data_ref": str(DB_PATH)},
    )
    return connected


def data_reference(
    resource_type: str,
    resource_id: str,
    *,
    allowed_actions: list[str] | None = None,
) -> dict[str, Any]:
    ref = {
        "ref_id": f"mock://l1.7/{resource_type}/{resource_id}",
        "resource_type": resource_type,
        "source_system": "monitor_reminder_local_mock",
        "version": "v0.8-stage3",
        "data_labels": ["internal", "mock"],
        "allowed_actions": allowed_actions or ["read"],
    }
    record_adapter_call(
        "data_module_1_7",
        "data.reference.issue",
        ref,
    )
    return ref
