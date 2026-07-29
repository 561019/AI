import pytest
from fastapi.testclient import TestClient

from analysis_prediction_engine.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "analysis-prediction-engine",
    }


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_non_health_routes_are_not_exposed(client: TestClient, path: str):
    assert client.get(path).status_code == 404
