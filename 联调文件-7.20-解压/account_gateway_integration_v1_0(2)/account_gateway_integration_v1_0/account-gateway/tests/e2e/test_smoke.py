from helpers import get


def test_stack_health_check(reset_state):
    response = get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
