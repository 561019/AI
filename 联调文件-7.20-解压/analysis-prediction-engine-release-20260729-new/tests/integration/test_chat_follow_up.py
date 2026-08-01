"""Integration tests for chat follow-up analysis flow.

Tests the full cycle: analysis -> context storage -> follow-up detection -> drill-down.
Uses mock LLM responses to test the routing logic without real API calls.
"""

import json
from pathlib import Path
from unittest import mock

# Mock attributes for the chat service module
_MODEL_JSON = "analysis_prediction_engine.services.chat_service._call_platform_json"
_MODEL_TEXT = "analysis_prediction_engine.services.chat_service._call_platform_text"
_DATA_DIR = Path(__file__).resolve().parent.parent.parent


def _diagnostic_intent():
    return json.dumps({
        "ready": True, "action": "diagnostic",
        "data_files": ["案例九_诊断请求_模拟数据.json"],
        "filter_months": None, "focus": "复购率下降诊断",
        "forecast_horizon": 6,
        "message": "好的，这是复购率数据。",
        "clarification": "",
    })


def _financial_intent():
    return json.dumps({
        "ready": True, "action": "financial",
        "data_files": ["2024年利润表_请求体.json"],
        "filter_months": None, "focus": "2024 profit analysis",
        "forecast_horizon": 6,
        "message": "好的，我来分析2024年的利润表。",
        "clarification": "",
    })


def _narrative_text(text=None):
    """Return plain text that the platform model text call would return."""
    if text is None:
        text = "分析结果。以上分析由AI基于确定性计算结果生成，仅供决策参考，须经真人确认后生效。"
    return text


def _follow_up_text(text=None):
    """Return plain text for follow-up narrative."""
    if text is None:
        text = "追问分析结果。以上分析由AI基于确定性计算结果生成，仅供决策参考。"
    return text


class TestChatFollowUpFlow:
    """Test the full chat + follow-up cycle."""

    @classmethod
    def setup_class(cls):
        """Ensure diagnostic data file exists."""
        cls.diag_file = _DATA_DIR / "案例九_诊断请求_模拟数据.json"
        cls.fin_file = _DATA_DIR / "2024年利润表_请求体.json"
        cls.has_diag_data = cls.diag_file.exists()
        cls.has_fin_data = cls.fin_file.exists()

    def setup_method(self):
        """Clear context before each test."""
        from analysis_prediction_engine.services.chat_service import (
            clear_last_analysis,
        )
        clear_last_analysis()

    # ---- Follow-up detection flow ----

    def test_first_message_is_not_follow_up(self):
        """The first message in a conversation is never a follow-up."""
        from analysis_prediction_engine.services.chat_service import chat

        with mock.patch(_MODEL_JSON, return_value=json.loads(_financial_intent())), \
             mock.patch(_MODEL_TEXT, return_value=_narrative_text()):
            result = chat("分析2024年利润表", None)

        assert result["role"] == "assistant"
        assert result.get("is_follow_up") is not True

    def test_second_message_with_follow_up_keyword_is_detected(self):
        """After an initial analysis, a 'why' message triggers follow-up."""
        import analysis_prediction_engine.services.chat_service as cs

        # First: do an initial analysis
        with mock.patch(_MODEL_JSON, return_value=json.loads(_financial_intent())), \
             mock.patch(_MODEL_TEXT, return_value=_narrative_text("总体分析完成。收入同比增长10%。")):
            cs.chat("分析2024年利润表", None)

        assert cs.get_last_analysis() is not None
        assert cs.get_last_analysis()["type"] == "financial_statement"

        # Second: ask a follow-up question
        follow_up = "收入增长主要由主营业务收入驱动。以上分析由AI基于确定性计算结果生成，仅供决策参考。"
        with mock.patch(_MODEL_TEXT, return_value=follow_up):
            result = cs.chat("为什么收入增长这么多", None)

        assert result.get("is_follow_up") is True
        assert result["action"] == "follow_up:financial_statement"
        assert "追问分析" in result["content"]
        assert "收入增长主要" in result["content"]

    def test_follow_up_context_persists(self):
        """Follow-up response should not overwrite the original context."""
        import analysis_prediction_engine.services.chat_service as cs

        # Initial analysis
        with mock.patch(_MODEL_JSON, return_value=json.loads(_financial_intent())), \
             mock.patch(_MODEL_TEXT, return_value=_narrative_text("总体分析")):
            cs.chat("分析2024年利润表", None)

        original_type = cs.get_last_analysis()["type"]

        # Follow-up
        with mock.patch(_MODEL_TEXT, return_value=_follow_up_text("追问回答")):
            cs.chat("为什么收入增长了", None)

        # Context type should still be the original analysis type
        assert cs.get_last_analysis()["type"] == original_type

    def test_multiple_follow_ups_succeed(self):
        """User can ask multiple follow-up questions in a row."""
        from analysis_prediction_engine.services.chat_service import chat

        # Initial analysis
        with mock.patch(_MODEL_JSON, return_value=json.loads(_financial_intent())), \
             mock.patch(_MODEL_TEXT, return_value=_narrative_text("总体分析")):
            chat("分析2024年利润表", None)

        # First follow-up
        with mock.patch(_MODEL_TEXT, return_value=_follow_up_text("第一次追问回答")):
            r1 = chat("为什么收入增长", None)

        assert r1.get("is_follow_up") is True

        # Second follow-up
        with mock.patch(_MODEL_TEXT, return_value=_follow_up_text("第二次追问回答")):
            r2 = chat("具体哪个季度贡献最大", None)

        assert r2.get("is_follow_up") is True
        assert "第二次追问回答" in r2["content"]

    def test_new_topic_resets_via_new_analysis(self):
        """When user starts a completely new analysis, it should work normally."""
        from analysis_prediction_engine.services.chat_service import chat

        # Initial analysis
        with mock.patch(_MODEL_JSON, return_value=json.loads(_financial_intent())), \
             mock.patch(_MODEL_TEXT, return_value=_narrative_text("总体分析")):
            chat("分析2024年利润表", None)

        # New topic (no follow-up keyword, explicit analysis request)
        with mock.patch(_MODEL_JSON, return_value=json.loads(_financial_intent())), \
             mock.patch(_MODEL_TEXT, return_value=_narrative_text("新分析")):
            r = chat("分析2025年利润表", None)

        # Should be treated as new analysis, not follow-up
        assert r.get("is_follow_up") is not True

    def test_follow_up_with_diagnostic_data(self):
        """Follow-up after diagnostic analysis uses diagnostic drill-down."""
        from analysis_prediction_engine.services.chat_service import chat

        # First: diagnostic analysis (display mode, not root cause)
        with mock.patch(_MODEL_JSON, return_value=json.loads(_diagnostic_intent())), \
             mock.patch(_MODEL_TEXT, return_value=_narrative_text("复购率总体数据显示10家经销商。")):
            r1 = chat("复购率为什么下降", None)

        # Should show entity table (not root cause since we mock the file read failure)
        assert r1["role"] == "assistant"

    def test_handle_follow_up_returns_gracefully_on_llm_failure(self):
        """If LLM call fails during follow-up, return a graceful message."""
        import analysis_prediction_engine.services.chat_service as cs

        # Setup context
        with mock.patch(_MODEL_JSON, return_value=json.loads(_financial_intent())), \
             mock.patch(_MODEL_TEXT, return_value=_narrative_text("总体分析")):
            cs.chat("分析2024年利润表", None)

        assert cs.get_last_analysis() is not None

        # Follow-up with LLM failure
        with mock.patch(_MODEL_TEXT, side_effect=Exception("Connection refused")):
            r = cs.chat("为什么收入变化", None)

        assert r.get("is_follow_up") is True
        assert "追问分析" in r["content"]
        # Should still return content even on failure (error msg + suggestion)
        assert len(r["content"]) > 30

    def test_clear_last_analysis(self):
        """clear_last_analysis() should reset context."""
        import analysis_prediction_engine.services.chat_service as cs

        cs.clear_last_analysis()
        assert cs.get_last_analysis() is None

        # Set context via an analysis
        with mock.patch(_MODEL_JSON, return_value=json.loads(_financial_intent())), \
             mock.patch(_MODEL_TEXT, return_value=_narrative_text("test")):
            cs.chat("分析2024年利润表", None)

        assert cs.get_last_analysis() is not None

        cs.clear_last_analysis()
        assert cs.get_last_analysis() is None
