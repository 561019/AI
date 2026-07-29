from pydantic import TypeAdapter

from app.schemas.intent_result import IntentAnalysisResult
from app.schemas.task import TaskItem, TaskList
from app.services.task_builder import TaskListBuilder


def test_build_from_intent_result_creates_single_task() -> None:
    builder = TaskListBuilder()
    intent_result = IntentAnalysisResult.matched_result(
        function_code="REPORT_CREATE",
        intent_category="report_generation",
        target_engine="report_engine",
        confidence=1.0,
        record_id="record-001",
    )

    task_list = builder.build_from_intent_result(
        intent_result=intent_result,
        user_id="user-001",
        function_name="Report Generation",
    )

    assert task_list.request_id == "record-001"
    assert task_list.user_id == "user-001"
    assert task_list.analysis_level == 1
    assert task_list.overall_confidence == 1.0
    assert len(task_list.tasks) == 1
    assert task_list.tasks[0].function_code == "REPORT_CREATE"
    assert task_list.tasks[0].function_name == "Report Generation"
    assert task_list.tasks[0].parameters == {}


def test_build_from_intent_result_supports_additional_tasks() -> None:
    builder = TaskListBuilder()
    intent_result = IntentAnalysisResult.matched_result(
        function_code="REPORT_CREATE",
        intent_category="report_generation",
        target_engine="report_engine",
        confidence=0.95,
        record_id="record-001",
    )
    second_task = TaskItem(
        function_code="MESSAGE_SEND",
        function_name="Send Message",
        intent_category="workflow",
        target_engine="workflow_engine",
        parameters={"receiver": "manager"},
        dependency=[],
        priority=2,
        confidence=0.8,
    )

    task_list = builder.build_from_intent_result(
        intent_result=intent_result,
        user_id="user-001",
        function_name="Report Generation",
        additional_tasks=[second_task],
    )

    assert len(task_list.tasks) == 2
    assert task_list.tasks[1].function_code == "MESSAGE_SEND"
    assert task_list.overall_confidence == 0.8


def test_build_from_intent_result_returns_empty_tasks_when_unmatched() -> None:
    builder = TaskListBuilder()

    task_list = builder.build_from_intent_result(
        intent_result=IntentAnalysisResult.unmatched(),
        user_id="user-001",
        request_id="record-unmatched",
    )

    assert task_list.request_id == "record-unmatched"
    assert task_list.tasks == []
    assert task_list.analysis_level == 1
    assert task_list.overall_confidence == 0


def test_build_from_intent_result_accepts_empty_parameters() -> None:
    builder = TaskListBuilder()
    intent_result = IntentAnalysisResult.matched_result(
        function_code="DATA_SUMMARY",
        intent_category="data_processing",
        target_engine="data_engine",
        confidence=0.9,
        record_id="record-002",
    )

    task_list = builder.build_from_intent_result(
        intent_result=intent_result,
        user_id="user-002",
        function_name="Data Summary",
        parameters=None,
    )

    assert task_list.tasks[0].parameters == {}


def test_task_list_json_schema_contains_required_fields() -> None:
    schema = TaskList.model_json_schema()

    assert "request_id" in schema["properties"]
    assert "user_id" in schema["properties"]
    assert "tasks" in schema["properties"]
    assert "analysis_level" in schema["properties"]
    assert "overall_confidence" in schema["properties"]
    assert "created_at" in schema["properties"]


def test_task_item_json_schema_contains_required_fields() -> None:
    schema = TaskItem.model_json_schema()

    assert "task_id" in schema["properties"]
    assert "function_code" in schema["properties"]
    assert "function_name" in schema["properties"]
    assert "intent_category" in schema["properties"]
    assert "target_engine" in schema["properties"]
    assert "parameters" in schema["properties"]
    assert "dependency" in schema["properties"]
    assert "priority" in schema["properties"]
    assert "confidence" in schema["properties"]


def test_task_list_validates_from_json_payload() -> None:
    payload = {
        "request_id": "request-001",
        "user_id": "user-001",
        "analysis_level": 1,
        "overall_confidence": 1.0,
        "created_at": "2026-07-09T00:00:00Z",
        "tasks": [
            {
                "task_id": "task-001",
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
    }

    task_list = TypeAdapter(TaskList).validate_python(payload)

    assert task_list.request_id == "request-001"
    assert task_list.tasks[0].function_code == "REPORT_CREATE"
