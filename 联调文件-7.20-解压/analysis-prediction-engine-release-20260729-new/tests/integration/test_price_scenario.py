import json
from decimal import Decimal
from pathlib import Path

from analysis_prediction_engine.contracts.requests import PriceForecastRequest
from analysis_prediction_engine.services.price_forecast import forecast_prices


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "material_price_anonymized.json"


def test_anonymized_price_scenario_has_reference_only_forecast() -> None:
    request = PriceForecastRequest.model_validate(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))

    result = forecast_prices(request)

    assert result["trace_id"] == "scenario-price-001"
    assert result["decision_reference_only"] is True
    assert result["volatility"]["trend"] == "up"
    assert result["forecasts"][0]["value"] == Decimal("18.00")
    assert result["uncertainty"]["status"] == "available"
    assert all(item["source_record_ids"] for item in result["forecasts"])
