from fastapi.testclient import TestClient

from analysis_prediction_engine.main import app


def test_engine_exposes_no_intent_aggregation_reporting_or_notification_routes() -> None:
    client = TestClient(app)

    for path in (
        "/v1/intents/parse",
        "/v1/datasets/aggregate",
        "/v1/reports/generate",
        "/v1/notifications/send",
        "/v1/external-records/write",
    ):
        assert client.post(path, json={}).status_code == 404
