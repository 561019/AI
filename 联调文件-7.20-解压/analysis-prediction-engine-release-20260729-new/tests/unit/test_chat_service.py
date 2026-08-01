"""Tests for chat_service — clarification mechanism and helper functions."""

import json
from unittest import mock

from analysis_prediction_engine.services.chat_service import _build_history_text, chat

_CALL_JSON_ATTR = "analysis_prediction_engine.services.chat_service._call_platform_json"
_CALL_TEXT_ATTR = "analysis_prediction_engine.services.chat_service._call_platform_text"


# ---- _build_history_text tests ----

def test_build_history_returns_placeholder_for_none():
    assert "no previous conversation" in _build_history_text(None)


def test_build_history_returns_placeholder_for_empty_list():
    assert "no previous conversation" in _build_history_text([])


def test_build_history_formats_single_user_turn():
    history = [{"role": "user", "content": "帮我分析2024年利润表"}]
    result = _build_history_text(history)
    assert "[用户]: 帮我分析2024年利润表" in result


def test_build_history_formats_multiple_turns():
    history = [
        {"role": "user", "content": "帮我分析一下经营数据"},
        {"role": "assistant", "content": "请问您想分析哪个年度的数据？"},
        {"role": "user", "content": "2024年的"},
    ]
    result = _build_history_text(history)
    assert "[用户]: 帮我分析一下经营数据" in result
    assert "[系统]: 请问您想分析哪个年度的数据？" in result
    assert "[用户]: 2024年的" in result


def test_build_history_truncates_long_messages():
    history = [{"role": "user", "content": "A" * 500}]
    result = _build_history_text(history)
    assert "..." in result
    assert len(result) < 600


def test_build_history_caps_at_last_6_turns():
    history = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
    result = _build_history_text(history)
    assert "msg 0" not in result
    assert "msg 9" in result


# ---- chat() platform model failure ----

def test_chat_returns_clarification_when_platform_model_unavailable():
    with mock.patch(_CALL_JSON_ATTR, side_effect=Exception("platform model unavailable")):
        result = chat("帮我分析2024年利润表", None)
    assert result["role"] == "assistant"
    assert result["action"] == "clarify"


# ---- chat() intent parsing failure (LLM network error) ----

def test_chat_returns_clarification_on_llm_failure():
    with mock.patch(_CALL_JSON_ATTR, side_effect=Exception("Connection refused")):
        result = chat("帮我分析一下", None)

    assert result["role"] == "assistant"
    assert result["action"] == "clarify"
    assert "请问" in result["content"] or "可用的数据文件" in result["content"]


# ---- clarification flow: ready=false ----

def test_chat_returns_clarification_when_ready_is_false():
    clarification_json = (
        '{"ready":false,"action":"","data_files":[],'
        '"filter_months":null,"focus":"","forecast_horizon":6,'
        '"message":"",'
        '"clarification":"请问您想分析哪个年度的财务报表？2023、2024还是2025年？"}'
    )

    with mock.patch(_CALL_JSON_ATTR, return_value=json.loads(clarification_json)):
        result = chat("帮我分析财务报表", None)

    assert result["role"] == "assistant"
    assert result["action"] == "clarify"
    assert "2023" in result["content"]
    assert "财务报表" in result["content"]


def test_chat_appends_file_list_when_no_files_matched():
    clarification_json = (
        '{"ready":false,"action":"","data_files":[],'
        '"filter_months":null,"focus":"","forecast_horizon":6,'
        '"message":"","clarification":"请问您想分析什么内容？"}'
    )

    with mock.patch(_CALL_JSON_ATTR, return_value=json.loads(clarification_json)):
        result = chat("分析", None)

    assert result["action"] == "clarify"
    assert "可用的数据文件" in result["content"]


def test_empty_clarification_gets_default_message():
    """When LLM returns ready=false with empty clarification, use a default."""
    clarification_json = (
        '{"ready":false,"action":"","data_files":[],'
        '"filter_months":null,"focus":"","forecast_horizon":6,'
        '"message":"","clarification":""}'
    )

    with mock.patch(_CALL_JSON_ATTR, return_value=json.loads(clarification_json)):
        result = chat("帮我分析", None)

    assert result["action"] == "clarify"
    assert len(result["content"]) > 10  # Should have a default message


# ---- clarification flow: ready=true (proceed to full analysis) ----

def test_chat_proceeds_to_analysis_when_ready_is_true():
    intent_json = (
        '{"ready":true,"action":"financial",'
        '"data_files":["2024年利润表_请求体.json"],'
        '"filter_months":null,'
        '"focus":"2024 profit trend analysis",'
        '"forecast_horizon":6,'
        '"message":"好的，我来分析2024年的利润表。",'
        '"clarification":""}'
    )

    narrative_text = "营业收入同比增长，整体经营向好。⚠️ 以上分析由AI基于确定性计算结果生成，仅供决策参考，须经真人确认后生效。"

    with mock.patch(_CALL_JSON_ATTR, return_value=json.loads(intent_json)), \
         mock.patch(_CALL_TEXT_ATTR, return_value=narrative_text):
        result = chat("帮我分析2024年利润表", None)

    assert result["role"] == "assistant"
    assert result["action"] == "financial"
    assert "2024年利润表_请求体.json" in result["data_files"]
    assert "AI 分析" in result["content"]


def test_chat_uses_history_for_context():
    history = [
        {"role": "user", "content": "帮我分析数据"},
        {"role": "assistant", "content": "请问您想分析哪个年度的什么数据？"},
    ]

    intent_json = (
        '{"ready":true,"action":"financial",'
        '"data_files":["2025年利润表_请求体.json"],'
        '"filter_months":null,'
        '"focus":"2025 profit analysis",'
        '"forecast_horizon":6,'
        '"message":"好的",'
        '"clarification":""}'
    )

    narrative_text = "2025年利润表分析结果。⚠️ 以上分析由AI基于确定性计算结果生成，仅供决策参考，须经真人确认后生效。"

    with mock.patch(_CALL_JSON_ATTR, return_value=json.loads(intent_json)), \
         mock.patch(_CALL_TEXT_ATTR, return_value=narrative_text):
        result = chat("2025年的利润表", history)

    assert result["role"] == "assistant"
    assert result["action"] == "financial"
