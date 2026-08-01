"""Integration tests: diagnostic analysis via evaluate and analyze endpoints."""

import json
from decimal import Decimal

from fastapi.testclient import TestClient

from analysis_prediction_engine.main import app

client = TestClient(app)

DIAGNOSTIC_PAYLOAD = {
    "schema_version": "v1",
    "trace_id": "trace-api-diag-001",
    "analysis_type": "diagnostic",
    "target": {
        "metric": "repurchase_rate",
        "change": "-2.0",
        "unit": "percentage_points",
        "description": "六月前十名经销商本季度复购率环比降两个点",
    },
    "entities": [
        {"entity_id": "D001", "entity_name": "经销商A", "contribution": "-1.2"},
        {"entity_id": "D002", "entity_name": "经销商B", "contribution": "-0.6"},
        {"entity_id": "D003", "entity_name": "经销商C", "contribution": "-0.15"},
        {"entity_id": "D004", "entity_name": "经销商D", "contribution": "-0.05"},
    ],
    "evidence": [
        {"evidence_id": "E001", "entity_id": "D001", "evidence_type": "delivery_delay",
         "summary": "6月中旬配送延误5天", "source_ref": "log:event:D001:001", "date": "2026-06-15"},
        {"evidence_id": "E002", "entity_id": "D001", "evidence_type": "follow_up_missed",
         "summary": "回访逾期未完成", "source_ref": "log:followup:D001:005", "date": "2026-06-20"},
        {"evidence_id": "E003", "entity_id": "D002", "evidence_type": "delivery_delay",
         "summary": "配送延误3天", "source_ref": "log:event:D002:002", "date": "2026-06-18"},
    ],
    "top_n": 2,
}


def test_evaluate_diagnostic_returns_correct_structure():
    resp = client.post("/v1/analysis-jobs/evaluate", json=DIAGNOSTIC_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis_type"] == "diagnostic"
    assert body["trace_id"] == "trace-api-diag-001"
    assert body["decision_reference_only"] is True
    assert body["human_confirmation_required"] is True
    assert body["effective"] is False
    assert len(body["major_contributors"]) == 2
    assert body["major_contributors"][0]["entity_id"] == "D001"
    assert body["major_contributors"][0]["rank"] == 1
    assert body["major_contributors"][1]["entity_id"] == "D002"
    assert len(body["root_cause_hypotheses"]) >= 1
    assert len(body["conclusions"]) >= 1
    assert len(body["provenance"]) >= 1
    assert len(body["calculation_metadata"]) >= 1


def test_evaluate_diagnostic_top_1_returns_one_contributor():
    payload = {**DIAGNOSTIC_PAYLOAD, "top_n": 1}
    resp = client.post("/v1/analysis-jobs/evaluate", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["major_contributors"]) == 1
    assert body["major_contributors"][0]["entity_id"] == "D001"


def test_evaluate_diagnostic_rejects_missing_target():
    payload = {
        "schema_version": "v1",
        "trace_id": "x",
        "analysis_type": "diagnostic",
        "entities": [{"entity_id": "D001", "entity_name": "A"}],
    }
    resp = client.post("/v1/analysis-jobs/evaluate", json=payload)
    assert resp.status_code == 422


def test_evaluate_diagnostic_rejects_empty_entities():
    payload = {
        "schema_version": "v1",
        "trace_id": "x",
        "analysis_type": "diagnostic",
        "target": {"metric": "x", "change": "0", "description": "test"},
        "entities": [],
    }
    resp = client.post("/v1/analysis-jobs/evaluate", json=payload)
    assert resp.status_code == 422


def test_analyze_diagnostic_returns_computation_and_narrative():
    """POST /v1/analysis-jobs/analyze should return computation + narrative."""
    resp = client.post("/v1/analysis-jobs/analyze", json=DIAGNOSTIC_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert "computation" in body
    assert "narrative" in body
    assert body["computation"]["analysis_type"] == "diagnostic"
    assert len(body["computation"]["major_contributors"]) == 2
    # narrative may be skipped/error if no API key, or complete
    assert body["narrative"]["analysis_type"] == "diagnostic"
