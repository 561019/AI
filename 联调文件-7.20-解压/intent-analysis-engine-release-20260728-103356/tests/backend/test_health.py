from fastapi.testclient import TestClient

from app.api.routes import health
from app.main import app


client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_check_returns_ok_when_dependencies_are_available(monkeypatch) -> None:
    monkeypatch.setattr(health, "_check_database", lambda: {"status": "ok"})
    monkeypatch.setattr(health, "_check_milvus", lambda: {"status": "ok", "version": "test"})

    response = client.get("/health/ready")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["milvus"]["status"] == "ok"


def test_readiness_check_returns_503_when_dependency_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(health, "_check_database", lambda: {"status": "ok"})
    monkeypatch.setattr(health, "_check_milvus", lambda: {"status": "error", "message": "offline"})

    response = client.get("/health/ready")

    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "degraded"
    assert body["checks"]["milvus"]["message"] == "offline"
