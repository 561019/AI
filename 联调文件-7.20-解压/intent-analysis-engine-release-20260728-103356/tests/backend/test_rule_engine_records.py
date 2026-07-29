from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.models import FunctionRegistry, RuleMapping
from app.services.rule_engine import RuleMatcher


def make_rule(keyword: str, function_code: str, *, pattern: str | None = None) -> RuleMapping:
    return RuleMapping(
        keyword=keyword,
        pattern=pattern,
        function_code=function_code,
        priority=10,
        status="active",
        created_at=datetime.now(UTC),
    )


def make_function(function_code: str = "REPORT_CREATE") -> FunctionRegistry:
    return FunctionRegistry(
        function_code=function_code,
        function_name="报告生成",
        intent_category="报告生成型",
        target_engine="report_engine",
        description="报告生成能力。",
        required_parameters={},
        example_sentences=[],
        status="active",
    )


def test_rule_matcher_records_successful_match() -> None:
    rule_repository = MagicMock()
    rule_repository.list_active_rules.return_value = [
        make_rule("生成报告", "REPORT_CREATE", pattern=r"生成.*报告"),
    ]
    function_repository = MagicMock()
    function_repository.get_by_code.return_value = make_function()
    intent_record_service = MagicMock()
    matcher = RuleMatcher(
        rule_repository=rule_repository,
        function_registry_repository=function_repository,
        intent_record_service=intent_record_service,
    )

    result = matcher.match("生成销售报告", user_id="user-1", conversation_id="conversation-1")

    assert result.matched is True
    intent_record_service.record_rule_match_result.assert_called_once()
    call_kwargs = intent_record_service.record_rule_match_result.call_args.kwargs
    assert call_kwargs["request_text"] == "生成销售报告"
    assert call_kwargs["user_id"] == "user-1"
    assert call_kwargs["conversation_id"] == "conversation-1"
    assert call_kwargs["match_result"] is result
    assert call_kwargs["cost_time"] >= 0


def test_rule_matcher_records_unmatched_result() -> None:
    rule_repository = MagicMock()
    rule_repository.list_active_rules.return_value = [
        make_rule("生成报告", "REPORT_CREATE", pattern=r"生成.*报告"),
    ]
    function_repository = MagicMock()
    intent_record_service = MagicMock()
    matcher = RuleMatcher(
        rule_repository=rule_repository,
        function_registry_repository=function_repository,
        intent_record_service=intent_record_service,
    )

    result = matcher.match("今天天气怎么样", user_id="user-1", conversation_id="conversation-1")

    assert result.matched is False
    intent_record_service.record_rule_match_result.assert_called_once()
    call_kwargs = intent_record_service.record_rule_match_result.call_args.kwargs
    assert call_kwargs["match_result"] is result


def test_rule_matcher_records_blank_input_when_record_service_exists() -> None:
    matcher = RuleMatcher(
        rule_repository=MagicMock(),
        function_registry_repository=MagicMock(),
        intent_record_service=MagicMock(),
    )

    result = matcher.match(" ", user_id="user-1", conversation_id="conversation-1")

    assert result.matched is False
    matcher.intent_record_service.record_rule_match_result.assert_called_once()


def test_rule_matcher_keeps_existing_usage_without_record_service() -> None:
    rule_repository = MagicMock()
    rule_repository.list_active_rules.return_value = []
    matcher = RuleMatcher(
        rule_repository=rule_repository,
        function_registry_repository=MagicMock(),
    )

    result = matcher.match("今天天气怎么样")

    assert result.matched is False
