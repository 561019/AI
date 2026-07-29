from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_intent_analysis_returns_placeholder_response() -> None:
    response = client.post(
        "/api/intent-analysis",
        json={
            "request_text": "calculate commission",
            "real_user_id": "tester",
            "conversation_id": "conversation-1",
        },
    )

    body = response.json()

    assert response.status_code == 200
    assert body["result_type"] == "safeguard"
    assert body["task_list"] is None
    assert body["tracking_id"]
