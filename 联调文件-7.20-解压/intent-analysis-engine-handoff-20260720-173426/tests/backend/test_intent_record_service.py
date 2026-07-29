from unittest.mock import MagicMock

import pytest

from app.models import IntentRecord
from app.schemas.rule_engine import RuleMatchResult
from app.services.intent_record_service import (
    IntentRecordService,
    IntentRecordValidationError,
)


def make_record(user_id: str = "user-1", level: str = "1", result: str = "success") -> IntentRecord:
    return IntentRecord(
        request_text="生成销售报告",
        user_id=user_id,
        conversation_id="conversation-1",
        analysis_level=level,
        matched_function="REPORT_CREATE",
        confidence=1.0,
        result=result,
        cost_time=10,
    )


def make_service() -> IntentRecordService:
    repository = MagicMock()
    service = IntentRecordService(repository)
    return service


def test_record_intent_result_creates_success_record() -> None:
    service = make_service()
    service.repository.create_record.side_effect = lambda record: record

    result = service.record_intent_result(
        request_text="生成销售报告",
        user_id="user-1",
        conversation_id="conversation-1",
        analysis_level=1,
        matched_function="REPORT_CREATE",
        confidence=1.0,
        result="success",
        cost_time=11,
    )

    assert result.request_text == "生成销售报告"
    assert result.analysis_level == "1"
    assert result.matched_function == "REPORT_CREATE"
    assert result.confidence == 1.0
    assert result.result == "success"
    assert result.cost_time == 11
    service.repository.create_record.assert_called_once()


def test_record_intent_result_creates_unmatched_record() -> None:
    service = make_service()
    service.repository.create_record.side_effect = lambda record: record

    result = service.record_intent_result(
        request_text="今天天气怎么样",
        user_id="user-1",
        conversation_id="conversation-1",
        analysis_level=1,
        matched_function=None,
        confidence=None,
        result="unmatched",
    )

    assert result.matched_function is None
    assert result.confidence is None
    assert result.result == "unmatched"


@pytest.mark.parametrize("level", [1, "1", 2, "2", 3, "3"])
def test_record_intent_result_accepts_different_levels(level: int | str) -> None:
    service = make_service()
    service.repository.create_record.side_effect = lambda record: record

    result = service.record_intent_result(
        request_text="测试请求",
        user_id="user-1",
        conversation_id="conversation-1",
        analysis_level=level,
        matched_function=None,
        confidence=None,
        result="unmatched",
    )

    assert result.analysis_level == str(level)


def test_record_rule_match_result_maps_matched_result_to_success() -> None:
    service = make_service()
    service.repository.create_record.side_effect = lambda record: record
    match_result = RuleMatchResult.matched_result(
        function_code="REPORT_CREATE",
        intent_category="报告生成型",
        target_engine="report_engine",
        confidence=1.0,
    )

    result = service.record_rule_match_result(
        request_text="生成销售报告",
        user_id="user-1",
        conversation_id="conversation-1",
        match_result=match_result,
        cost_time=7,
    )

    assert result.analysis_level == "1"
    assert result.matched_function == "REPORT_CREATE"
    assert result.result == "success"
    assert result.cost_time == 7


def test_record_rule_match_result_maps_unmatched_result() -> None:
    service = make_service()
    service.repository.create_record.side_effect = lambda record: record

    result = service.record_rule_match_result(
        request_text="今天天气怎么样",
        user_id="user-1",
        conversation_id="conversation-1",
        match_result=RuleMatchResult.unmatched(),
    )

    assert result.analysis_level == "1"
    assert result.matched_function is None
    assert result.result == "unmatched"


def test_get_analysis_history_queries_by_user() -> None:
    service = make_service()
    records = [make_record(user_id="user-2")]
    service.repository.query_by_user.return_value = records

    result = service.get_analysis_history(user_id="user-2")

    assert result == records
    service.repository.query_by_user.assert_called_once_with("user-2", limit=100, offset=0)


def test_get_analysis_history_queries_by_level() -> None:
    service = make_service()
    records = [make_record(level="2")]
    service.repository.query_by_level.return_value = records

    result = service.get_analysis_history(analysis_level=2, limit=10)

    assert result == records
    service.repository.query_by_level.assert_called_once_with(2, limit=10, offset=0)


def test_get_analysis_history_lists_records_by_default() -> None:
    service = make_service()
    records = [make_record()]
    service.repository.list_records.return_value = records

    result = service.get_analysis_history(limit=5, offset=1)

    assert result == records
    service.repository.list_records.assert_called_once_with(limit=5, offset=1)


@pytest.mark.parametrize(
    "field_name, overrides",
    [
        ("request_text", {"request_text": ""}),
        ("user_id", {"user_id": " "}),
        ("conversation_id", {"conversation_id": ""}),
        ("analysis_level", {"analysis_level": ""}),
        ("result", {"result": ""}),
    ],
)
def test_record_intent_result_rejects_missing_required_fields(
    field_name: str,
    overrides: dict,
) -> None:
    service = make_service()
    payload = {
        "request_text": "生成销售报告",
        "user_id": "user-1",
        "conversation_id": "conversation-1",
        "analysis_level": 1,
        "matched_function": "REPORT_CREATE",
        "confidence": 1.0,
        "result": "success",
    }
    payload.update(overrides)

    with pytest.raises(IntentRecordValidationError, match=field_name):
        service.record_intent_result(**payload)
