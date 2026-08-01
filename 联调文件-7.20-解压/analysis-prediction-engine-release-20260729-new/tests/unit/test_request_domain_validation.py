from decimal import Decimal

import pytest
from pydantic import ValidationError

from analysis_prediction_engine.contracts.requests import (
    BusinessMetricRequest,
    FinancialStatementRequest,
    PriceForecastRequest,
)


def test_price_request_rejects_short_history_nonpositive_price_and_duplicate_date() -> None:
    common = {
        "schema_version": "v1",
        "trace_id": "price-validation",
        "analysis_type": "price_forecast",
        "forecast_horizon": 1,
    }
    with pytest.raises(ValidationError):
        PriceForecastRequest.model_validate(
            {**common, "records": [{"date": "2026-01-01", "source_record_id": "p1", "price": "10"}]}
        )
    with pytest.raises(ValidationError):
        PriceForecastRequest.model_validate(
            {
                **common,
                "records": [
                    {"date": "2026-01-01", "source_record_id": "p1", "price": "10"},
                    {"date": "2026-02-01", "source_record_id": "p2", "price": "0"},
                    {"date": "2026-03-01", "source_record_id": "p3", "price": "12"},
                ],
            }
        )
    with pytest.raises(ValidationError):
        PriceForecastRequest.model_validate(
            {
                **common,
                "records": [
                    {"date": "2026-01-01", "source_record_id": "p1", "price": "10"},
                    {"date": "2026-01-01", "source_record_id": "p2", "price": "11"},
                    {"date": "2026-03-01", "source_record_id": "p3", "price": "12"},
                ],
            }
        )
    with pytest.raises(ValidationError):
        PriceForecastRequest.model_validate(
            {
                **common,
                "records": [
                    {"date": "2026-01-01", "source_record_id": "same", "price": "10"},
                    {"date": "2026-02-01", "source_record_id": "same", "price": "11"},
                    {"date": "2026-03-01", "source_record_id": "p3", "price": "12"},
                ],
            }
        )
    with pytest.raises(ValidationError):
        PriceForecastRequest.model_validate(
            {
                **common,
                "forecast_horizon": 1,
                "records": [
                    {"date": "9999-10-01", "source_record_id": "p1", "price": "10"},
                    {"date": "9999-11-01", "source_record_id": "p2", "price": "11"},
                    {"date": "9999-12-01", "source_record_id": "p3", "price": "12"},
                ],
            }
        )


def test_financial_request_requires_valid_unique_periods_and_deeply_immutable_metrics() -> None:
    payload = {
        "schema_version": "v1",
        "trace_id": "financial-validation",
        "analysis_type": "financial_statement",
        "records": [
            {"period": "2026-01", "source_record_id": "f1", "metrics": {"revenue": "10"}},
            {"period": "2026-02", "source_record_id": "f2", "metrics": {"revenue": "11"}},
        ],
    }
    request = FinancialStatementRequest.model_validate(payload)
    with pytest.raises(TypeError):
        request.records[0].metrics["revenue"] = Decimal("99")
    with pytest.raises(ValidationError):
        FinancialStatementRequest.model_validate(
            {**payload, "records": [{"period": "2026-99", "source_record_id": "f1", "metrics": {"revenue": "10"}}]}
        )
    with pytest.raises(ValidationError):
        FinancialStatementRequest.model_validate(
            {**payload, "records": [payload["records"][0], payload["records"][0]]}
        )


def test_business_request_requires_exact_target_limit_set() -> None:
    payload = {
        "schema_version": "v1",
        "trace_id": "business-validation",
        "analysis_type": "business_metric",
        "record": {
            "period": "2026-06",
            "source_record_id": "b1",
            "revenue": "100",
            "sales_cost": "40",
            "delivery_cost": "15",
            "operating_cost": "20",
        },
    }
    with pytest.raises(ValidationError):
        BusinessMetricRequest.model_validate({**payload, "target_limits": {"sales_cost_ratio": "35"}})
    with pytest.raises(ValidationError):
        BusinessMetricRequest.model_validate(
            {
                **payload,
                "target_limits": {
                    "sales_cost_ratio": "35",
                    "delivery_cost_ratio": "20",
                    "operating_cost_ratio": "25",
                    "unknown": "10",
                },
            }
        )
