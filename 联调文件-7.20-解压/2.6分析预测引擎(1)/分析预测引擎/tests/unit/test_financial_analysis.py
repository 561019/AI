from decimal import Decimal

from analysis_prediction_engine.contracts.requests import FinancialStatementRequest
from analysis_prediction_engine.services.financial_analysis import analyze_financial_statement


def test_financial_analysis_returns_traceable_structured_conclusions() -> None:
    request = FinancialStatementRequest.model_validate(
        {
            "schema_version": "v1",
            "trace_id": "trace-financial-001",
            "analysis_type": "financial_statement",
            "records": [
                {
                    "period": "2025-06",
                    "source_record_id": "statement-2025-06",
                    "metrics": {
                        "revenue": "100",
                        "net_income": "10",
                        "total_assets": "200",
                        "equity": "100",
                    },
                },
                {
                    "period": "2026-05",
                    "source_record_id": "statement-2026-05",
                    "metrics": {
                        "revenue": "120",
                        "net_income": "12",
                        "total_assets": "220",
                        "equity": "110",
                    },
                },
                {
                    "period": "2026-06",
                    "source_record_id": "statement-2026-06",
                    "metrics": {
                        "revenue": "150",
                        "net_income": "15",
                        "total_assets": "250",
                        "equity": "125",
                    },
                },
            ],
        }
    )

    result = analyze_financial_statement(request)

    assert result["analysis_type"] == "financial_statement"
    assert result["trace_id"] == "trace-financial-001"
    assert result["decision_reference_only"] is True
    assert result["metrics"]["revenue"]["year_over_year_percent"] == Decimal("50.00")
    assert result["metrics"]["revenue"]["period_over_period_percent"] == Decimal("25.00")
    assert result["dupont"]["roe_percent"] == Decimal("12.00")
    assert any(
        item.output_field == "financial.revenue.year_over_year_percent"
        for item in result["provenance"]
    )


def test_financial_analysis_uses_metric_specific_prior_period_for_period_comparison() -> None:
    request = FinancialStatementRequest.model_validate(
        {
            "schema_version": "v1",
            "trace_id": "trace-financial-sparse",
            "analysis_type": "financial_statement",
            "records": [
                {"period": "2026-04", "source_record_id": "cash-apr", "metrics": {"cash": "100"}},
                {"period": "2026-05", "source_record_id": "cash-may", "metrics": {"cash": "110"}},
                {"period": "2026-06", "source_record_id": "other-jun", "metrics": {"revenue": "200"}},
            ],
        }
    )

    result = analyze_financial_statement(request)

    assert result["metrics"]["cash"]["period_over_period_percent"] == Decimal("10.00")
    cash_period_provenance = [
        item
        for item in result["provenance"]
        if item.output_field == "financial.cash.period_over_period_percent"
    ]
    assert {item.source_record_id for item in cash_period_provenance} == {"cash-apr", "cash-may"}


def test_financial_analysis_does_not_label_year_gap_as_period_over_period() -> None:
    request = FinancialStatementRequest.model_validate(
        {
            "schema_version": "v1",
            "trace_id": "trace-financial-gap",
            "analysis_type": "financial_statement",
            "records": [
                {"period": "2025-06", "source_record_id": "old", "metrics": {"revenue": "100"}},
                {"period": "2026-06", "source_record_id": "new", "metrics": {"revenue": "150"}},
            ],
        }
    )

    result = analyze_financial_statement(request)

    assert result["metrics"]["revenue"]["year_over_year_percent"] == Decimal("50.00")
    assert result["metrics"]["revenue"]["period_over_period_percent"] is None
    assert result["metrics"]["revenue"]["period_over_period_status"] == "not_computable"


def test_financial_analysis_returns_not_computable_for_zero_or_missing_base() -> None:
    request = FinancialStatementRequest.model_validate(
        {
            "schema_version": "v1",
            "trace_id": "trace-financial-zero",
            "analysis_type": "financial_statement",
            "records": [
                {"period": "2025-06", "source_record_id": "old", "metrics": {"revenue": "0"}},
                {"period": "2026-06", "source_record_id": "new", "metrics": {"revenue": "100"}},
            ],
        }
    )

    result = analyze_financial_statement(request)

    assert result["metrics"]["revenue"]["year_over_year_percent"] is None
    assert result["metrics"]["revenue"]["year_over_year_status"] == "not_computable"
    assert result["metrics"]["revenue"]["period_over_period_percent"] is None
