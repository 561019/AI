from unittest.mock import MagicMock

import pytest

from app.models import FunctionRegistry, IntentRecord
from app.schemas.rule_engine import RuleMatchResult
from app.services.intent_analyzer import Level1IntentAnalyzer


def make_function(function_code: str = "REPORT_CREATE") -> FunctionRegistry:
    return FunctionRegistry(
        function_code=function_code,
        function_name="Report Generation",
        intent_category="report_generation",
        target_engine="report_engine",
        description="Report generation capability.",
        required_parameters={},
        example_sentences=[],
        status="active",
    )


def make_record(record_id: str = "record-001", result: str = "success") -> IntentRecord:
    record = IntentRecord(
        request_text="create sales report",
        user_id="user-001",
        conversation_id="conversation-001",
        analysis_level="1",
        matched_function="REPORT_CREATE" if result == "success" else None,
        confidence=1.0 if result == "success" else 0,
        result=result,
        cost_time=1,
    )
    record.id = record_id
    return record


def build_analyzer(
    *,
    match_result: RuleMatchResult,
    function: FunctionRegistry | None = None,
    record: IntentRecord | None = None,
) -> tuple[Level1IntentAnalyzer, MagicMock, MagicMock, MagicMock]:
    rule_matcher = MagicMock()
    rule_matcher.match.return_value = match_result

    function_registry_service = MagicMock()
    function_registry_service.validate_function_status.return_value = function or make_function()

    intent_record_service = MagicMock()
    intent_record_service.record_intent_result.return_value = record or make_record()

    analyzer = Level1IntentAnalyzer(
        rule_matcher=rule_matcher,
        function_registry_service=function_registry_service,
        intent_record_service=intent_record_service,
    )
    return analyzer, rule_matcher, function_registry_service, intent_record_service


@pytest.mark.parametrize(
    "text",
    [
        "create sales report",
        "create monthly report",
        "query sales data",
        "calculate commission",
        "summarize sales rows",
        "create finance report",
        "query payment data",
        "calculate regional commission",
        "summarize product data",
        "create operations report",
    ],
)
def test_level1_analyzer_successful_rule_matches_return_task_list(text: str) -> None:
    match_result = RuleMatchResult.matched_result(
        function_code="REPORT_CREATE",
        intent_category="report_generation",
        target_engine="report_engine",
        confidence=1.0,
    )
    analyzer, rule_matcher, function_service, record_service = build_analyzer(
        match_result=match_result,
        function=make_function("REPORT_CREATE"),
        record=make_record("record-success"),
    )

    task_list = analyzer.analyze(
        text=text,
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert task_list.request_id == "record-success"
    assert task_list.user_id == "user-001"
    assert task_list.analysis_level == 1
    assert task_list.overall_confidence == 1.0
    assert len(task_list.tasks) == 1
    task = task_list.tasks[0]
    assert task.function_code == "REPORT_CREATE"
    assert task.function_name == "Report Generation"
    assert task.intent_category == "report_generation"
    assert task.target_engine == "report_engine"
    assert task.parameters == {}
    assert task.dependency == []
    assert task.priority == 1
    assert task.confidence == 1.0
    rule_matcher.match.assert_called_once_with(text, record=False)
    function_service.validate_function_status.assert_called_once_with("REPORT_CREATE")
    record_service.record_intent_result.assert_called_once()


@pytest.mark.parametrize(
    "text",
    [
        "what is the weather today",
        "will it rain tomorrow",
        "tell me a joke",
        "play music",
        "order coffee",
        "chat with me",
        "who are you",
        "buy lottery ticket",
        "play a movie",
        "unknown request",
    ],
)
def test_level1_analyzer_unmatched_results_return_empty_task_list(text: str) -> None:
    analyzer, rule_matcher, function_service, record_service = build_analyzer(
        match_result=RuleMatchResult.unmatched(),
        record=make_record("record-unmatched", result="unmatched"),
    )

    task_list = analyzer.analyze(
        text=text,
        user_id="user-002",
        conversation_id="conversation-002",
    )

    assert task_list.model_dump(exclude={"created_at"}) == {
        "request_id": "record-unmatched",
        "user_id": "user-002",
        "tasks": [],
        "analysis_level": 1,
        "overall_confidence": 0.0,
    }
    rule_matcher.match.assert_called_once_with(text, record=False)
    function_service.validate_function_status.assert_not_called()
    record_service.record_intent_result.assert_called_once()


def test_level1_analyzer_uses_function_registry_as_source_of_task_details() -> None:
    match_result = RuleMatchResult.matched_result(
        function_code="DATA_QUERY",
        intent_category="old_category",
        target_engine="old_engine",
        confidence=0.9,
    )
    function = make_function("DATA_QUERY")
    function.function_name = "Data Query"
    function.intent_category = "intelligent_qa"
    function.target_engine = "knowledge_qa_engine"
    analyzer, _, _, _ = build_analyzer(
        match_result=match_result,
        function=function,
        record=make_record("record-query"),
    )

    task_list = analyzer.analyze(
        text="query sales data",
        user_id="user-003",
        conversation_id="conversation-003",
    )

    assert task_list.tasks[0].function_code == "DATA_QUERY"
    assert task_list.tasks[0].function_name == "Data Query"
    assert task_list.tasks[0].intent_category == "intelligent_qa"
    assert task_list.tasks[0].target_engine == "knowledge_qa_engine"
    assert task_list.tasks[0].confidence == 0.9


def test_level1_analyzer_task_list_schema_matches_expected_output_shape() -> None:
    match_result = RuleMatchResult.matched_result(
        function_code="REPORT_CREATE",
        intent_category="report_generation",
        target_engine="report_engine",
        confidence=1.0,
    )
    analyzer, _, _, _ = build_analyzer(
        match_result=match_result,
        record=make_record("record-xyz"),
    )

    task_list = analyzer.analyze(
        text="create sales report",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    dumped = task_list.model_dump(
        exclude={
            "created_at": True,
            "tasks": {"__all__": {"task_id": True}},
        },
    )
    assert dumped == {
        "request_id": "record-xyz",
        "user_id": "user-001",
        "tasks": [
            {
                "function_code": "REPORT_CREATE",
                "function_name": "Report Generation",
                "intent_category": "report_generation",
                "target_engine": "report_engine",
                "parameters": {},
                "dependency": [],
                "priority": 1,
                "confidence": 1.0,
            },
        ],
        "analysis_level": 1,
        "overall_confidence": 1.0,
    }
