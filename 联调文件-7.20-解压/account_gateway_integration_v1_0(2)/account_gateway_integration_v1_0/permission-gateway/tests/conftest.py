from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def app(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'permission.sqlite3').as_posix()}",
        logs_dir=tmp_path / "logs",
        mechanism_secret="test-mechanism-secret",
    )
    return create_app(settings)


@pytest.fixture()
def client(app):
    with TestClient(app, headers={
        "X-L1-Caller-Service": "l1_internal_channel",
        "X-L1-Mechanism-Secret": "test-mechanism-secret",
    }) as test_client:
        yield test_client


@pytest.fixture()
def admin_headers():
    return {
        "X-Actor-ID": "platform-admin",
        "X-Actor-Roles": "hanhe_admin,hanhe_im,hanhe_dsm",
        "X-Tenant-ID": "tenant-a",
    }


@pytest.fixture()
def check_payload():
    return {
        "trace_id": "trace-1",
        "request_id": "request-1",
        "actor_id": "u-1",
        "action": "content.generate",
        "source_service": "intent_engine",
        "target_service": "content_engine",
        "data_label": "normal",
        "data_state": "active",
        "tenant_id": "tenant-a",
        "ingress_mode": "mechanism_direct",
        "transfer_id": "transfer-1",
    }


def command(client: TestClient, headers: dict[str, str], path: str, action: str, payload: dict):
    return client.post(path, headers=headers, json={"action": action, "payload": payload})


@pytest.fixture()
def command_fn():
    return command
