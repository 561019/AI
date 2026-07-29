from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.audit import write_fallback
from tests.test_contract import seed_position_permission


def test_decision_audit_is_append_only(
    app, client, admin_headers, command_fn, check_payload
):
    seed_position_permission(client, admin_headers, command_fn)
    client.post("/api/permission/check", json=check_payload)
    database = app.state.database
    with pytest.raises(DBAPIError):
        with database.engine.begin() as connection:
            connection.execute(
                text("UPDATE permission_decisions SET reason='changed' WHERE id=1")
            )
    with pytest.raises(DBAPIError):
        with database.engine.begin() as connection:
            connection.execute(text("DELETE FROM permission_decisions WHERE id=1"))


def test_fallback_log_is_append_only_ndjson(app):
    path = app.state.settings.logs_dir / "permission-fallback.ndjson"
    write_fallback(app.state.settings.logs_dir, {"trace_id": "trace-a", "result": "error"})
    write_fallback(app.state.settings.logs_dir, {"trace_id": "trace-b", "result": "error"})
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["trace_id"] for row in rows] == ["trace-a", "trace-b"]


def test_database_unavailable_fails_closed_and_writes_fallback(app, client, check_payload):
    database = app.state.database
    database_path = Path(database.engine.url.database)
    database.dispose()
    database_path.unlink()
    response = client.post("/api/permission/check", json=check_payload)
    assert response.status_code == 503
    assert response.json()["allowed"] is False
    assert response.json()["result"] == "error"
    assert response.json()["reason_code"] == "PERMISSION_DB_ERROR"
    fallback = app.state.settings.logs_dir / "permission-fallback.ndjson"
    row = json.loads(fallback.read_text(encoding="utf-8").splitlines()[-1])
    assert row["trace_id"] == check_payload["trace_id"]
    assert row["reason_code"] == "PERMISSION_DB_ERROR"
