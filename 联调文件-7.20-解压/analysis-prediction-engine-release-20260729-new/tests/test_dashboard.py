from fastapi.testclient import TestClient

from analysis_prediction_engine.main import app


def test_dashboard_is_available_without_expanding_engine_api_surface() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "分析预测引擎" in response.text
    assert "财务经营分析" in response.text
    assert "原料价格预测" in response.text
    assert "经营指标分析" in response.text
    assert "仅供决策参考" in response.text
