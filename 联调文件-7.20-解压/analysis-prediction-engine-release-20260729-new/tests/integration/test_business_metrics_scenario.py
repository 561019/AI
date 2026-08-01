import json
from decimal import Decimal
from pathlib import Path

from analysis_prediction_engine.contracts.requests import BusinessMetricRequest
from analysis_prediction_engine.services.business_metrics import analyze_business_metrics


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "law_firm_metrics_anonymized.json"


def test_anonymized_law_firm_scenario_produces_alert_candidates_only() -> None:
    request = BusinessMetricRequest.model_validate(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))

    result = analyze_business_metrics(request)

    assert result["trace_id"] == "scenario-law-firm-001"
    assert result["net_profit"] == Decimal("250000.00")
    assert result["cost_ratios"]["sales_cost_ratio"] == Decimal("40.00")
    assert result["alert_candidates"][0]["metric"] == "sales_cost_ratio"
    assert "notification" not in result
    assert result["decision_reference_only"] is True
