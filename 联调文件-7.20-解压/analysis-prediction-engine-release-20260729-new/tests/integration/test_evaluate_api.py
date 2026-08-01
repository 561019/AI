from fastapi.testclient import TestClient

from analysis_prediction_engine.main import app


def test_valid_financial_request_returns_structured_analysis() -> None:
    client = TestClient(app)

    response = client.post(
        "/v1/analysis-jobs/evaluate",
        json={
            "schema_version": "v1",
            "trace_id": "trace-api-001",
            "analysis_type": "financial_statement",
            "records": [
                {
                    "period": "2025-06",
                    "source_record_id": "financial-2025-06",
                    "metrics": {"revenue": "1000.00"},
                },
                {
                    "period": "2026-06",
                    "source_record_id": "financial-2026-06",
                    "metrics": {"revenue": "1500.00"},
                },
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["trace_id"] == "trace-api-001"
    assert response.json()["analysis_type"] == "financial_statement"
    assert response.json()["decision_reference_only"] is True
    assert response.json()["metrics"]["revenue"]["year_over_year_percent"] == "50.00"


def test_valid_price_and_business_requests_return_structured_results() -> None:
    client = TestClient(app)
    price_response = client.post(
        "/v1/analysis-jobs/evaluate",
        json={
            "schema_version": "v1",
            "trace_id": "trace-api-price",
            "analysis_type": "price_forecast",
            "forecast_horizon": 1,
            "records": [
                {"date": "2026-01-01", "source_record_id": "p1", "price": "10"},
                {"date": "2026-02-01", "source_record_id": "p2", "price": "12"},
                {"date": "2026-03-01", "source_record_id": "p3", "price": "14"},
            ],
        },
    )
    business_response = client.post(
        "/v1/analysis-jobs/evaluate",
        json={
            "schema_version": "v1",
            "trace_id": "trace-api-business",
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
        },
    )

    assert price_response.status_code == 200
    assert price_response.json()["forecasts"][0]["value"] == "16.00"
    assert business_response.status_code == 200
    assert business_response.json()["alert_candidates"][0]["metric"] == "sales_cost_ratio"


def test_semantically_invalid_request_returns_traceable_validation_error() -> None:
    client = TestClient(app)

    response = client.post(
        "/v1/analysis-jobs/evaluate",
        json={
            "schema_version": "v1",
            "trace_id": "trace-api-invalid",
            "analysis_type": "price_forecast",
            "forecast_horizon": 1,
            "records": [{"date": "2026-01-01", "source_record_id": "p1", "price": "10"}],
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "schema_version": "v1",
        "trace_id": "trace-api-invalid",
        "code": "VALIDATION_ERROR",
        "message": "request validation failed",
    }


def test_malformed_json_returns_validation_error_without_reparsing_body() -> None:
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/v1/analysis-jobs/evaluate",
        content="{",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "request validation failed",
    }


def test_zero_revenue_business_request_returns_not_computable_result() -> None:
    client = TestClient(app)

    response = client.post(
        "/v1/analysis-jobs/evaluate",
        json={
            "schema_version": "v1",
            "trace_id": "trace-api-business-zero",
            "analysis_type": "business_metric",
            "record": {
                "period": "2026-06",
                "source_record_id": "b-zero",
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
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "not_computable"
    assert response.json()["metric_status"] == "not_computable"
    assert response.json()["cost_ratios"] is None


def test_unquoted_json_number_is_rejected_to_preserve_decimal_input_fidelity() -> None:
    client = TestClient(app)

    response = client.post(
        "/v1/analysis-jobs/evaluate",
        json={
            "schema_version": "v1",
            "trace_id": "trace-api-float",
            "analysis_type": "financial_statement",
            "records": [
                {"period": "2025-06", "source_record_id": "f1", "metrics": {"revenue": 0.12345678901234568}},
                {"period": "2026-06", "source_record_id": "f2", "metrics": {"revenue": 0.22345678901234567}},
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["trace_id"] == "trace-api-float"


def test_unquoted_json_integer_and_oversized_decimal_are_rejected() -> None:
    client = TestClient(app)
    integer_response = client.post(
        "/v1/analysis-jobs/evaluate",
        json={
            "schema_version": "v1",
            "trace_id": "trace-api-integer",
            "analysis_type": "financial_statement",
            "records": [
                {"period": "2025-06", "source_record_id": "f1", "metrics": {"revenue": 9007199254740993}},
                {"period": "2026-06", "source_record_id": "f2", "metrics": {"revenue": "100"}},
            ],
        },
    )
    oversized_response = client.post(
        "/v1/analysis-jobs/evaluate",
        json={
            "schema_version": "v1",
            "trace_id": "trace-api-oversized",
            "analysis_type": "financial_statement",
            "records": [
                {"period": "2025-06", "source_record_id": "f1", "metrics": {"revenue": "1e100000"}},
                {"period": "2026-06", "source_record_id": "f2", "metrics": {"revenue": "100"}},
            ],
        },
    )

    assert integer_response.status_code == 422
    assert integer_response.json()["trace_id"] == "trace-api-integer"
    assert oversized_response.status_code == 422
    assert oversized_response.json()["trace_id"] == "trace-api-oversized"


def test_http_response_preserves_large_decimal_as_canonical_string() -> None:
    client = TestClient(app)

    response = client.post(
        "/v1/analysis-jobs/evaluate",
        json={
            "schema_version": "v1",
            "trace_id": "trace-api-large-decimal",
            "analysis_type": "business_metric",
            "record": {
                "period": "2026-06",
                "source_record_id": "b-large",
                "revenue": "9007199254740993",
                "sales_cost": "0",
                "delivery_cost": "0",
                "operating_cost": "0",
            },
            "target_limits": {
                "sales_cost_ratio": "35",
                "delivery_cost_ratio": "20",
                "operating_cost_ratio": "25",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["net_profit"] == "9007199254740993.00"
