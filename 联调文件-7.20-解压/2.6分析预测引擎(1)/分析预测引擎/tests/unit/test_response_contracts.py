from analysis_prediction_engine.contracts.requests import (
    BusinessMetricRequest,
    FinancialStatementRequest,
    PriceForecastRequest,
)
from analysis_prediction_engine.contracts.responses import (
    BusinessMetricResult,
    FinancialAnalysisResult,
    PriceForecastResult,
    validate_analysis_response,
)
from analysis_prediction_engine.services.business_metrics import analyze_business_metrics
from analysis_prediction_engine.services.financial_analysis import analyze_financial_statement
from analysis_prediction_engine.services.price_forecast import forecast_prices


def test_financial_service_result_conforms_to_public_contract_with_conclusions() -> None:
    result = analyze_financial_statement(
        FinancialStatementRequest.model_validate(
            {
                "schema_version": "v1",
                "trace_id": "response-financial",
                "analysis_type": "financial_statement",
                "records": [
                    {"period": "2025-06", "source_record_id": "f1", "metrics": {"revenue": "100"}},
                    {"period": "2026-06", "source_record_id": "f2", "metrics": {"revenue": "150"}},
                ],
            }
        )
    )

    validated = validate_analysis_response(result)

    assert isinstance(validated, FinancialAnalysisResult)
    assert validated.conclusions
    assert validated.conclusions[0].kind == "financial_metric"


def test_price_service_result_conforms_to_public_contract_with_conclusions() -> None:
    result = forecast_prices(
        PriceForecastRequest.model_validate(
            {
                "schema_version": "v1",
                "trace_id": "response-price",
                "analysis_type": "price_forecast",
                "forecast_horizon": 1,
                "records": [
                    {"date": "2026-01-01", "source_record_id": "p1", "price": "10"},
                    {"date": "2026-02-01", "source_record_id": "p2", "price": "12"},
                    {"date": "2026-03-01", "source_record_id": "p3", "price": "14"},
                ],
            }
        )
    )

    validated = validate_analysis_response(result)

    assert isinstance(validated, PriceForecastResult)
    assert validated.conclusions
    assert validated.conclusions[0].kind == "price_trend_forecast"


def test_business_service_result_conforms_to_public_contract_with_conclusions() -> None:
    result = analyze_business_metrics(
        BusinessMetricRequest.model_validate(
            {
                "schema_version": "v1",
                "trace_id": "response-business",
                "analysis_type": "business_metric",
                "record": {
                    "period": "2026-06",
                    "source_record_id": "b1",
                    "revenue": "100",
                    "sales_cost": "40",
                    "delivery_cost": "15",
                    "operating_cost": "20",
                },
                "target_limits": {
                    "sales_cost_ratio": "35",
                    "delivery_cost_ratio": "20",
                    "operating_cost_ratio": "25",
                },
            }
        )
    )

    validated = validate_analysis_response(result)

    assert isinstance(validated, BusinessMetricResult)
    assert validated.conclusions
    assert validated.conclusions[0].kind == "business_target_comparison"
