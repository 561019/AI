import json
from decimal import Decimal
from pathlib import Path

from analysis_prediction_engine.contracts.requests import FinancialStatementRequest
from analysis_prediction_engine.services.financial_analysis import analyze_financial_statement


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "financial_statement_anonymized.json"


def test_anonymized_financial_scenario_produces_traceable_decision_reference() -> None:
    request = FinancialStatementRequest.model_validate(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))

    result = analyze_financial_statement(request)

    assert result["trace_id"] == "scenario-financial-001"
    assert result["decision_reference_only"] is True
    assert result["metrics"]["revenue"]["year_over_year_percent"] == Decimal("50.00")
    assert result["metrics"]["revenue"]["period_over_period_percent"] == Decimal("20.00")
    assert result["dupont"]["roe_percent"] == Decimal("12.00")
    assert all(reference.source_record_id.startswith("anon-fin-") for reference in result["provenance"])
