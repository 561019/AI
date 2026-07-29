import json
import sqlite3
import time
from pathlib import Path

import requests

from helpers import layer_dispatch, permission_url
from l1_support import prepare_identity, prepare_identity_runtime_contract, unique


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DB = PROJECT_ROOT / ".e2e-data" / "audit.db"


def test_permission_decision_writes_traceable_audit_record():
    account_id, position_id, trace_id = unique("audit-account"), unique("audit-position"), unique("audit-trace")
    prepare_identity(account_id, position_id)
    prepare_identity_runtime_contract(position_id, grant=True)
    response = layer_dispatch(
        account_id=account_id,
        action="identity.context.read_self",
        resource_type="identity_context",
        resource_id=account_id,
        trace_id=trace_id,
    )
    assert response.status_code == 200
    audit = requests.get(f"{permission_url()}/api/permission/audits", params={"trace_id": trace_id}, timeout=2)
    assert audit.status_code == 200
    row = audit.json()["audits"][0]
    assert row["actor_id"] == account_id
    assert row["result"] == "allow"
    assert row["reason_code"] == "PERMISSION_GRANTED"
    assert row["decision_id"] == response.json()["permission_decision_id"]


def _max_audit_id() -> int:
    with _connect() as db:
        return db.execute("SELECT COALESCE(MAX(id), 0) FROM audit_logs").fetchone()[0]


def _latest_audit_after(before_id: int) -> sqlite3.Row | None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with _connect() as db:
            row = db.execute(
                """
                SELECT
                    id,
                    actor_id,
                    action_type,
                    resource_type,
                    resource_id,
                    policy_decision,
                    policy_id,
                    context_snapshot,
                    version
                FROM audit_logs
                WHERE id > ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (before_id,),
            ).fetchone()
        if row is not None:
            return row
        time.sleep(0.02)
    return None


def _connect() -> sqlite3.Connection:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if AUDIT_DB.exists():
            db = sqlite3.connect(AUDIT_DB)
            db.row_factory = sqlite3.Row
            return db
        time.sleep(0.1)
    raise AssertionError(f"audit db was not created at {AUDIT_DB}")
