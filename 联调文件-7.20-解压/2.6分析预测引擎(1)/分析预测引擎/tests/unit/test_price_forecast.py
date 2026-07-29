from decimal import Decimal
from datetime import date

from analysis_prediction_engine.contracts.requests import PriceForecastRequest
from analysis_prediction_engine.services.price_forecast import forecast_prices


def test_price_forecast_is_deterministic_and_has_uncertainty() -> None:
    request = PriceForecastRequest.model_validate(
        {
            "schema_version": "v1",
            "trace_id": "trace-price-001",
            "analysis_type": "price_forecast",
            "forecast_horizon": 2,
            "records": [
                {"date": "2026-01-01", "source_record_id": "p1", "price": "10"},
                {"date": "2026-02-01", "source_record_id": "p2", "price": "12"},
                {"date": "2026-03-01", "source_record_id": "p3", "price": "14"},
            ],
        }
    )

    result = forecast_prices(request)

    assert result["analysis_type"] == "price_forecast"
    assert result["decision_reference_only"] is True
    assert result["uncertainty"]["status"] == "available"
    assert result["volatility"]["trend"] == "up"
    assert result["volatility"]["price_range"] == Decimal("4.00")
    assert result["volatility"]["relative_range_percent"] == Decimal("40.00")
    assert [item["value"] for item in result["forecasts"]] == [Decimal("16.00"), Decimal("18.00")]
    assert all(item["lower"] <= item["value"] <= item["upper"] for item in result["forecasts"])
    assert all(item["source_record_ids"] == ("p1", "p2", "p3") for item in result["forecasts"])


def test_price_forecast_does_not_emit_nonpositive_future_prices() -> None:
    request = PriceForecastRequest.model_validate(
        {
            "schema_version": "v1",
            "trace_id": "trace-price-declining",
            "analysis_type": "price_forecast",
            "forecast_horizon": 2,
            "records": [
                {"date": "2026-01-01", "source_record_id": "p1", "price": "3"},
                {"date": "2026-02-01", "source_record_id": "p2", "price": "2"},
                {"date": "2026-03-01", "source_record_id": "p3", "price": "1"},
            ],
        }
    )

    result = forecast_prices(request)

    assert result["status"] == "not_computable"
    assert result["forecasts"] == ()
    assert result["uncertainty"]["status"] == "not_computable"


def test_price_request_rejects_non_monthly_or_gapped_cadence() -> None:
    common = {
        "schema_version": "v1",
        "trace_id": "trace-price-cadence",
        "analysis_type": "price_forecast",
        "forecast_horizon": 1,
    }
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PriceForecastRequest.model_validate(
            {
                **common,
                "records": [
                    {"date": "2026-01-15", "source_record_id": "p1", "price": "10"},
                    {"date": "2026-02-15", "source_record_id": "p2", "price": "12"},
                    {"date": "2026-03-15", "source_record_id": "p3", "price": "14"},
                ],
            }
        )
    with pytest.raises(ValidationError):
        PriceForecastRequest.model_validate(
            {
                **common,
                "records": [
                    {"date": "2026-01-01", "source_record_id": "p1", "price": "10"},
                    {"date": "2026-03-01", "source_record_id": "p2", "price": "12"},
                    {"date": "2026-04-01", "source_record_id": "p3", "price": "14"},
                ],
            }
        )


def test_price_forecast_sorts_input_without_mutating_it() -> None:
    request = PriceForecastRequest.model_validate(
        {
            "schema_version": "v1",
            "trace_id": "trace-price-002",
            "analysis_type": "price_forecast",
            "forecast_horizon": 1,
            "records": [
                {"date": "2026-03-01", "source_record_id": "p3", "price": "14"},
                {"date": "2026-01-01", "source_record_id": "p1", "price": "10"},
                {"date": "2026-02-01", "source_record_id": "p2", "price": "12"},
            ],
        }
    )
    before = request.model_dump()

    result = forecast_prices(request)

    assert result["forecasts"][0]["value"] == Decimal("16.00")
    assert request.model_dump() == before
