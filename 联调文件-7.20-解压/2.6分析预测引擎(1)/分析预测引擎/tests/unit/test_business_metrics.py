from decimal import Decimal

from analysis_prediction_engine.contracts.requests import BusinessMetricRequest
from analysis_prediction_engine.services.business_metrics import analyze_business_metrics


def test_business_metrics_calculates_profit_ratios_and_alert_candidates() -> None:
    request = BusinessMetricRequest.model_validate(
        {
            "schema_version": "v1",
            "trace_id": "trace-business-001",
            "analysis_type": "business_metric",
            "record": {
                "period": "2026-06",
                "source_record_id": "metric-2026-06",
                "revenue": "1000",
                "sales_cost": "400",
                "delivery_cost": "150",
                "operating_cost": "200",
            },
            "target_limits": {
                "sales_cost_ratio": "35",
                "delivery_cost_ratio": "20",
                "operating_cost_ratio": "25",
            },
        }
    )

    result = analyze_business_metrics(request)

    assert result["net_profit"] == Decimal("250.00")
    assert result["cost_ratios"]["sales_cost_ratio"] == Decimal("40.00")
    assert result["cost_ratios"]["delivery_cost_ratio"] == Decimal("15.00")
    assert result["cost_ratios"]["operating_cost_ratio"] == Decimal("20.00")
    assert [item["metric"] for item in result["alert_candidates"]] == ["sales_cost_ratio"]
    assert result["decision_reference_only"] is True


def test_business_metrics_equal_threshold_is_not_exceeded() -> None:
    request = BusinessMetricRequest.model_validate(
        {
            "schema_version": "v1",
            "trace_id": "trace-business-002",
            "analysis_type": "business_metric",
            "record": {
                "period": "2026-06",
                "source_record_id": "metric-2026-06",
                "revenue": "1000",
                "sales_cost": "350",
                "delivery_cost": "200",
                "operating_cost": "250",
            },
            "target_limits": {
                "sales_cost_ratio": "35",
                "delivery_cost_ratio": "20",
                "operating_cost_ratio": "25",
            },
        }
    )

    result = analyze_business_metrics(request)

    assert result["alert_candidates"] == ()


def test_business_metrics_returns_not_computable_when_revenue_is_zero() -> None:
    request = BusinessMetricRequest.model_validate(
        {
            "schema_version": "v1",
            "trace_id": "trace-business-zero",
            "analysis_type": "business_metric",
            "record": {
                "period": "2026-06",
                "source_record_id": "metric-zero",
                "revenue": "0",
                "sales_cost": "0",
                "delivery_cost": "0",
                "operating_cost": "0",
            },
            "target_limits": {
                "sales_cost_ratio": "35",
                "delivery_cost_ratio": "20",
                "operating_cost_ratio": "25",
            },
        }
    )

    result = analyze_business_metrics(request)

    assert result["cost_ratios"] is None
    assert result["metric_status"] == "not_computable"
    assert result["alert_candidates"] == ()
