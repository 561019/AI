from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from analysis_prediction_engine.contracts.requests import (
    FinancialStatementRequest,
    PriceForecastRequest,
    parse_analysis_request,
)
from analysis_prediction_engine.contracts.responses import AnalysisResult


def test_financial_request_preserves_preaggregated_source_records() -> None:
    request = FinancialStatementRequest.model_validate(
        {
            "schema_version": "v1",
            "trace_id": "trace-fin-001",
            "analysis_type": "financial_statement",
            "records": [
                {
                    "period": "2026-06",
                    "source_record_id": "statement-2026-06",
                    "metrics": {"revenue": "1000.00"},
                }
            ],
        }
    )

    assert request.records[0].source_record_id == "statement-2026-06"
    assert request.records[0].metrics["revenue"] == Decimal("1000.00")
    with pytest.raises(ValidationError):
        request.trace_id = "changed"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "schema_version": "v1",
            "trace_id": "   ",
            "analysis_type": "financial_statement",
            "records": [
                {"period": "2026-06", "source_record_id": "r1", "metrics": {"revenue": "1"}}
            ],
        },
        {
            "schema_version": "v1",
            "trace_id": "trace-empty",
            "analysis_type": "price_forecast",
            "records": [],
        },
        {
            "schema_version": "v1",
            "trace_id": "trace-cross-type",
            "analysis_type": "price_forecast",
            "records": [
                {"date": "2026-06-01", "source_record_id": "price-1", "price": "18.50"}
            ],
            "target_limits": {"sales_cost_ratio": "35"},
        },
    ],
)
def test_invalid_or_cross_type_request_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        parse_analysis_request(payload)


def test_price_request_requires_valid_iso_date() -> None:
    with pytest.raises(ValidationError):
        PriceForecastRequest.model_validate(
            {
                "schema_version": "v1",
                "trace_id": "trace-price-001",
                "analysis_type": "price_forecast",
                "records": [{"date": "not-a-date", "source_record_id": "p1", "price": "10"}],
            }
        )


def test_analysis_result_rejects_non_reference_only_value() -> None:
    with pytest.raises(ValidationError):
        AnalysisResult(
            schema_version="v1",
            trace_id="trace-result-001",
            analysis_type="business_metric",
            conclusions=[],
            decision_reference_only=False,
        )

    result = AnalysisResult(
        schema_version="v1",
        trace_id="trace-result-001",
        analysis_type="business_metric",
        conclusions=[
            {
                "kind": "business_target_comparison",
                "status": "complete",
                "details": {},
            }
        ],
    )
    assert result.decision_reference_only is True
    with pytest.raises(ValidationError):
        result.trace_id = "changed"
