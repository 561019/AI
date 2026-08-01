"""Unit tests for follow_up service — detection, data preparation, and prompt building."""

from unittest import mock

from analysis_prediction_engine.services.follow_up import (
    is_follow_up,
    prepare_drilldown_data,
    build_follow_up_prompt,
)


# ---- is_follow_up tests ----

def test_is_follow_up_detects_why_keyword():
    prev = {"type": "diagnostic", "result": {}, "raw_data": {}}
    assert is_follow_up(prev, "为什么复购率下降了") is True


def test_is_follow_up_detects_cause_keyword():
    prev = {"type": "financial_statement", "result": {}, "raw_data": {}}
    assert is_follow_up(prev, "净利润变化的原因是什么") is True


def test_is_follow_up_detects_which_keyword():
    prev = {"type": "financial_statement", "result": {}, "raw_data": {}}
    assert is_follow_up(prev, "哪些指标变化最大") is True


def test_is_follow_up_detects_specific_keyword():
    prev = {"type": "price_forecast", "result": {}, "raw_data": {}}
    assert is_follow_up(prev, "具体说说5月的价格变化") is True


def test_is_follow_up_detects_explain_keyword():
    prev = {"type": "business_metric", "result": {}, "raw_data": {}}
    assert is_follow_up(prev, "解释一下成本为什么超标") is True


def test_is_follow_up_detects_deeper_keyword():
    prev = {"type": "diagnostic", "result": {}, "raw_data": {}}
    assert is_follow_up(prev, "进一步分析") is True


def test_is_follow_up_returns_false_without_context():
    assert is_follow_up(None, "为什么下降了") is False


def test_is_follow_up_returns_false_for_empty_message():
    prev = {"type": "diagnostic", "result": {}, "raw_data": {}}
    assert is_follow_up(prev, "") is False
    assert is_follow_up(prev, "   ") is False


def test_is_follow_up_returns_false_for_new_topic():
    """When user explicitly asks to analyze a new topic, it's not a follow-up."""
    prev = {"type": "diagnostic", "result": {}, "raw_data": {}}
    assert is_follow_up(prev, "分析一下2025年利润表") is False
    assert is_follow_up(prev, "看看钢材价格走势") is False
    assert is_follow_up(prev, "帮我预测一下下个季度需求") is False


def test_is_follow_up_returns_true_for_new_topic_with_follow_keyword():
    """When message has BOTH new-topic AND follow-up keywords, it IS a follow-up."""
    prev = {"type": "diagnostic", "result": {}, "raw_data": {}}
    assert is_follow_up(prev, "分析一下为什么复购率下降") is True
    assert is_follow_up(prev, "帮我看看具体是什么原因") is True


# ---- prepare_drilldown_data tests ----

_MOCK_FINANCIAL_RESULT = {
    "analysis_type": "financial_statement",
    "metrics": {
        "revenue": {
            "current": "1000000.00",
            "trend": "up",
            "trend_slope": "5000.00",
            "anomalies": ({"index": 2, "value": "850000", "z_score": "1.8"},),
            "by_period": (
                {"period": "2023-01", "value": "800000", "period_over_period_percent": None, "year_over_year_percent": None},
                {"period": "2023-02", "value": "820000", "period_over_period_percent": "2.50", "year_over_year_percent": None},
            ),
        },
    },
    "dupont": {
        "by_period": (
            {"period": "2023-02", "roe_percent": "15.00", "net_margin_percent": "10.00", "asset_turnover": "1.20", "equity_multiplier": "1.25"},
        ),
    },
}

_MOCK_PRICE_RESULT = {
    "analysis_type": "price_forecast",
    "volatility": {
        "slope": "50.00", "trend": "up",
        "price_range": "500.00", "relative_range_percent": "5.50",
        "model_version": "price-forecast-v1",
    },
    "forecasts": (
        {"step": 1, "date": "2023-07-01", "value": "1100.00", "lower": "1050.00", "upper": "1150.00"},
    ),
    "history_window": {"start": "2023-01-01", "end": "2023-06-01"},
    "uncertainty": {"message": "deterministic residual band"},
}

_MOCK_BUSINESS_RESULT = {
    "analysis_type": "business_metric",
    "net_profit": "200000.00",
    "cost_ratios": {
        "sales_cost_ratio": "60.00",
        "delivery_cost_ratio": "15.50",
        "operating_cost_ratio": "10.00",
    },
    "target_comparisons": {
        "sales_cost_ratio": {"target": "55.00", "difference": "5.00", "is_exceeded": True},
        "delivery_cost_ratio": {"target": "15.00", "difference": "0.50", "is_exceeded": True},
        "operating_cost_ratio": {"target": "12.00", "difference": "-2.00", "is_exceeded": False},
    },
    "alert_candidates": (
        {"metric": "sales_cost_ratio", "actual": "60.00", "target": "55.00", "excess": "5.00", "severity": "warning"},
    ),
}

_MOCK_DIAGNOSTIC_RESULT = {
    "analysis_type": "diagnostic",
    "major_contributors": (
        {"rank": 1, "entity_id": "D001", "entity_name": "经销商01", "contribution": "-12.0", "metrics": {"Q1_repurchase_rate": "50.0", "Q2_repurchase_rate": "38.0"}},
    ),
    "root_cause_hypotheses": (
        {"hypothesis_id": "H01", "description": "配送延误导致复购下降", "evidence_refs": ("E001", "E002"), "confidence": "plausible"},
    ),
}

_MOCK_DIAGNOSTIC_RAW = {
    "entities": [
        {"entity_id": "D001", "entity_name": "经销商01", "contribution": "-12.0", "metrics": {"Q1_repurchase_rate": "50.0", "Q2_repurchase_rate": "38.0"}},
        {"entity_id": "D002", "entity_name": "经销商02", "contribution": "-9.05", "metrics": {"Q1_repurchase_rate": "48.1", "Q2_repurchase_rate": "39.05"}},
    ],
    "evidence": [
        {"evidence_id": "E001", "entity_id": "D001", "evidence_type": "delivery_delay", "summary": "配送延误5天", "source_ref": "log:1", "date": "2026-06-15"},
    ],
}


def test_prepare_financial_drilldown():
    result = prepare_drilldown_data(_MOCK_FINANCIAL_RESULT, None, "financial_statement", "为什么")
    assert "逐期指标明细" in result
    assert "revenue" in result
    assert "异常检测" in result
    assert "杜邦分析" in result
    assert "ROE" in result


def test_prepare_price_drilldown():
    result = prepare_drilldown_data(_MOCK_PRICE_RESULT, None, "price_forecast", "为什么")
    assert "波动性指标" in result
    assert "预测区间明细" in result
    assert "up" in result


def test_prepare_business_drilldown():
    result = prepare_drilldown_data(_MOCK_BUSINESS_RESULT, None, "business_metric", "为什么")
    assert "净利润" in result
    assert "成本结构分解" in result
    assert "超标" in result
    assert "告警明细" in result


def test_prepare_diagnostic_drilldown_with_raw():
    result = prepare_drilldown_data(_MOCK_DIAGNOSTIC_RESULT, _MOCK_DIAGNOSTIC_RAW, "diagnostic", "为什么")
    assert "实体指标数据" in result
    assert "经销商01" in result
    assert "诊断证据记录" in result
    assert "E001" in result
    assert "原文:" in result or "原文：" in result  # verbatim evidence
    assert "已生成的根因假设" in result or "根因假设" in result
    assert "H01" in result
    # Should NOT contain calculated percentages that aren't in the data
    assert "25%" not in result.lower() or "25%" not in result  # no fabricated percentages


def test_prepare_drilldown_returns_placeholder_for_none_result():
    result = prepare_drilldown_data(None, None, "financial_statement", "test")
    assert "无上轮分析结果" in result


def test_prepare_generic_drilldown_falls_back():
    result = prepare_drilldown_data({"some": "data"}, {"raw": "stuff"}, "unknown_type", "test")
    assert len(result) > 0


# ---- build_follow_up_prompt tests ----

def test_build_follow_up_prompt():
    prompt = build_follow_up_prompt(
        "上轮分析摘要...", "下钻数据...", "为什么收入下降了", "financial_statement"
    )
    assert "system" in prompt
    assert "user" in prompt
    assert "上轮分析摘要" in prompt["user"]
    assert "下钻详细数据" in prompt["user"]
    assert "为什么收入下降了" in prompt["user"]
    assert "财务报表" in prompt["system"]


def test_build_follow_up_prompt_truncates_long_summary():
    long_summary = "A" * 2000
    prompt = build_follow_up_prompt(long_summary, "data", "question", "generic")
    assert len(prompt["user"]) < 2500  # Should be truncated
    assert "..." in prompt["user"]


def test_follow_up_keywords_coverage():
    """Verify all expected keywords are detected."""
    prev = {"type": "generic", "result": {}, "raw_data": {}}

    follow_up_messages = [
        "为什么收入下降",
        "什么原因导致的",
        "怎么回事复购率降了",
        "怎么会这样",
        "哪些指标异常",
        "哪个经销商影响最大",
        "具体说说看",
        "详细分析一下",
        "怎么降了这么多",
        "为何成本超标",
        "是因为配送问题吗",
        "进一步分析根因",
        "深入看看",
        "解释一下趋势",
        "说明原因",
        "展开讲讲",
        "细说一下",
        "是因为什么造成的",
        "什么原因",
        "什么导致的",
        "造成下降的原因",
    ]

    for msg in follow_up_messages:
        assert is_follow_up(prev, msg), f"Should detect follow-up: {msg}"
