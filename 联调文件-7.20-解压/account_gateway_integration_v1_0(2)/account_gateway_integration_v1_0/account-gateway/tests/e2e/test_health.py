from helpers import get


def test_health_returns_ok():
    response = get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
