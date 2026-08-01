"""Tests for diagnostic analysis service."""

from decimal import Decimal

from analysis_prediction_engine.contracts.requests import DiagnosticRequest
from analysis_prediction_engine.services.diagnostic import _parse_contribution, analyze_diagnostic


# ---- _parse_contribution ----

def test_parse_contribution_valid_decimal():
    assert _parse_contribution("3.5") == Decimal("3.5")


def test_parse_contribution_none_returns_zero():
    assert _parse_contribution(None) == Decimal("0")


def test_parse_contribution_invalid_returns_zero():
    assert _parse_contribution("abc") == Decimal("0")


def test_parse_contribution_uses_absolute_value():
    assert _parse_contribution("-4.2") == Decimal("4.2")


# ---- request validation ----

def test_diagnostic_request_smoke_test():
    req = DiagnosticRequest.model_validate({
        "schema_version": "v1",
        "trace_id": "trace-diag-001",
        "analysis_type": "diagnostic",
        "target": {
            "metric": "repurchase_rate",
            "change": "-2.0",
            "unit": "percentage_points",
            "description": "六月前十名经销商复购率环比下降",
        },
        "entities": [
            {"entity_id": "D001", "entity_name": "经销商A", "metrics": {"repurchase_rate_change": "-1.2"}, "contribution": "-1.2"},
            {"entity_id": "D002", "entity_name": "经销商B", "metrics": {"repurchase_rate_change": "-0.6"}, "contribution": "-0.6"},
            {"entity_id": "D003", "entity_name": "经销商C", "metrics": {"repurchase_rate_change": "-0.1"}, "contribution": "-0.1"},
        ],
        "evidence": [
            {"evidence_id": "E001", "entity_id": "D001", "evidence_type": "delivery_delay",
             "summary": "配送延误5天", "source_ref": "log:event:001", "date": "2026-06-15"},
            {"evidence_id": "E002", "entity_id": "D002", "evidence_type": "delivery_delay",
             "summary": "配送延误3天", "source_ref": "log:event:002", "date": "2026-06-18"},
        ],
        "top_n": 2,
    })
    assert req.analysis_type == "diagnostic"
    assert len(req.entities) == 3
    assert len(req.evidence) == 2
    assert req.top_n == 2


# ---- positioning (deterministic layer) ----

def test_positions_top_n_contributors():
    req = DiagnosticRequest.model_validate({
        "schema_version": "v1",
        "trace_id": "trace-diag-002",
        "analysis_type": "diagnostic",
        "target": {"metric": "repurchase_rate", "change": "-2.0", "description": "复购率下降"},
        "entities": [
            {"entity_id": "D001", "entity_name": "A", "contribution": "-1.2"},
            {"entity_id": "D002", "entity_name": "B", "contribution": "-0.6"},
            {"entity_id": "D003", "entity_name": "C", "contribution": "-0.1"},
            {"entity_id": "D004", "entity_name": "D", "contribution": "-0.05"},
        ],
        "top_n": 2,
    })
    result = analyze_diagnostic(req)
    contributors = result["major_contributors"]
    assert len(contributors) == 2
    assert contributors[0]["entity_id"] == "D001"
    assert contributors[0]["rank"] == 1
    assert contributors[1]["entity_id"] == "D002"
    assert contributors[1]["rank"] == 2


def test_missing_contribution_ranks_lower():
    req = DiagnosticRequest.model_validate({
        "schema_version": "v1",
        "trace_id": "trace-diag-003",
        "analysis_type": "diagnostic",
        "target": {"metric": "repurchase_rate", "change": "-2.0", "description": "test"},
        "entities": [
            {"entity_id": "D001", "entity_name": "A"},
            {"entity_id": "D002", "entity_name": "B", "contribution": "-0.5"},
        ],
        "top_n": 1,
    })
    result = analyze_diagnostic(req)
    assert result["major_contributors"][0]["entity_id"] == "D002"


# ---- output structure ----

def test_diagnostic_result_has_required_metadata():
    req = DiagnosticRequest.model_validate({
        "schema_version": "v1",
        "trace_id": "trace-diag-004",
        "analysis_type": "diagnostic",
        "target": {"metric": "repurchase_rate", "change": "-2.0", "description": "test"},
        "entities": [
            {"entity_id": "D001", "entity_name": "A", "contribution": "-1.2"},
            {"entity_id": "D002", "entity_name": "B", "contribution": "-0.6"},
        ],
        "evidence": [
            {"evidence_id": "E001", "entity_id": "D001", "evidence_type": "delivery_delay",
             "summary": "配送延误", "source_ref": "log:1"},
        ],
    })
    result = analyze_diagnostic(req)
    assert result["analysis_type"] == "diagnostic"
    assert result["decision_reference_only"] is True
    assert result["human_confirmation_required"] is True
    assert result["effective"] is False
    assert len(result["major_contributors"]) == 2
    assert len(result["root_cause_hypotheses"]) >= 1
    for h in result["root_cause_hypotheses"]:
        assert len(h["description"]) > 0


def test_root_cause_hypotheses_have_evidence_refs():
    """Each hypothesis must reference evidence IDs — no empty claims (when LLM unavailable)."""
    req = DiagnosticRequest.model_validate({
        "schema_version": "v1",
        "trace_id": "trace-diag-005",
        "analysis_type": "diagnostic",
        "target": {"metric": "repurchase_rate", "change": "-2.0", "description": "test"},
        "entities": [
            {"entity_id": "D001", "entity_name": "A", "contribution": "-1.2"},
        ],
        "evidence": [
            {"evidence_id": "E001", "entity_id": "D001", "evidence_type": "delivery_delay",
             "summary": "配送延误5天", "source_ref": "log:1", "date": "2026-06-15"},
            {"evidence_id": "E002", "entity_id": "D001", "evidence_type": "follow_up_missed",
             "summary": "回访超期", "source_ref": "log:2", "date": "2026-06-20"},
        ],
    })
    result = analyze_diagnostic(req)
    for h in result["root_cause_hypotheses"]:
        if h["confidence"] != "uncertain":
            assert len(h["evidence_refs"]) > 0, f"Hypothesis {h['hypothesis_id']} has no evidence refs"


def test_provenance_includes_major_contributors():
    req = DiagnosticRequest.model_validate({
        "schema_version": "v1",
        "trace_id": "trace-diag-006",
        "analysis_type": "diagnostic",
        "target": {"metric": "repurchase_rate", "change": "-2.0", "description": "test"},
        "entities": [
            {"entity_id": "D001", "entity_name": "A", "contribution": "-1.2"},
            {"entity_id": "D002", "entity_name": "B", "contribution": "-0.6"},
        ],
        "top_n": 2,
    })
    result = analyze_diagnostic(req)
    contributor_provenance = [
        p for p in result["provenance"]
        if "diagnostic.major_contributors" in str(p.output_field)
    ]
    assert len(contributor_provenance) == 2


def test_no_evidence_produces_suggestion():
    """When no evidence, return at least one hypothesis noting evidence gap."""
    req = DiagnosticRequest.model_validate({
        "schema_version": "v1",
        "trace_id": "trace-diag-007",
        "analysis_type": "diagnostic",
        "target": {"metric": "repurchase_rate", "change": "-2.0", "description": "test"},
        "entities": [
            {"entity_id": "D001", "entity_name": "A", "contribution": "-1.2"},
        ],
    })
    result = analyze_diagnostic(req)
    assert len(result["root_cause_hypotheses"]) >= 1
    # When evidence is empty, the hypothesis should reflect that gap
    combined = " ".join(h["description"] for h in result["root_cause_hypotheses"]).lower()
    assert any(w in combined for w in ["证据", "无法", "不足", "补充"])
