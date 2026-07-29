from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.routes.intent import (
    get_clarification_session_manager,
    get_conversation_state_store,
    get_intent_analyzer,
    get_intent_record_service,
)
from app.main import app
from app.schemas.llm import NeedConfirmationResult
from app.schemas.task import TaskItem, TaskList
from app.services.conversation_understanding import InMemoryConversationStateStore
from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer
from app.services.intent_analysis_engine.clarification import ClarificationSessionManager


client = TestClient(app)


class FakeIntentAnalyzer:
    def __init__(self, result: TaskList | NeedConfirmationResult | Exception) -> None:
        self.result = result
        self.calls: list[dict] = []

    def analyze(
        self,
        *,
        text: str,
        user_id: str,
        conversation_id: str,
    ) -> TaskList | NeedConfirmationResult:
        self.calls.append(
            {
                "text": text,
                "user_id": user_id,
                "conversation_id": conversation_id,
            },
        )
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def analyze_with_debug(
        self,
        *,
        text: str,
        user_id: str,
        conversation_id: str,
    ) -> SimpleNamespace:
        result = self.analyze(
            text=text,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        debug = {
            "level1_result": result.model_dump(mode="json") if isinstance(result, TaskList) else None,
            "level2_result": None,
            "level3_result": result.model_dump(mode="json") if isinstance(result, NeedConfirmationResult) else None,
            "final_tasklist": result.model_dump(mode="json") if isinstance(result, TaskList) else None,
        }
        return SimpleNamespace(result=result, debug=debug)


class FakeIntentRecordService:
    def __init__(self, records: list[SimpleNamespace] | Exception) -> None:
        self.records = records
        self.calls: list[dict] = []

    def get_analysis_history(
        self,
        *,
        user_id: str | None = None,
        analysis_level: int | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SimpleNamespace]:
        self.calls.append(
            {
                "user_id": user_id,
                "analysis_level": analysis_level,
                "limit": limit,
                "offset": offset,
            },
        )
        if isinstance(self.records, Exception):
            raise self.records
        return self.records


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> None:
    app.dependency_overrides.clear()
    state_store = InMemoryConversationStateStore()
    app.dependency_overrides[get_conversation_state_store] = lambda: state_store
    yield
    app.dependency_overrides.clear()


def make_task_list() -> TaskList:
    return TaskList(
        request_id="record-001",
        user_id="user-001",
        tasks=[
            TaskItem(
                function_code="REPORT_CREATE",
                function_name="Report Create",
                intent_category="report_generation",
                target_engine="report_engine",
                parameters={},
                dependency=[],
                priority=1,
                confidence=0.96,
            ),
        ],
        analysis_level=1,
        overall_confidence=0.96,
    )


def make_record(record_id: str = "record-001") -> SimpleNamespace:
    return SimpleNamespace(
        id=record_id,
        request_text="create sales report",
        user_id="user-001",
        conversation_id="conversation-001",
        analysis_level="1",
        matched_function="REPORT_CREATE",
        confidence=0.96,
        result="success",
        cost_time=12,
        created_at=datetime(2026, 7, 9, tzinfo=UTC),
    )


def test_analyze_endpoint_returns_unified_success_response() -> None:
    fake_analyzer = FakeIntentAnalyzer(make_task_list())
    app.dependency_overrides[get_intent_analyzer] = lambda: fake_analyzer

    response = client.post(
        "/api/v1/intent/analyze",
        json={
            "text": "create sales report",
            "user_id": "user-001",
            "conversation_id": "conversation-001",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["request_id"] == "record-001"
    assert body["data"]["analysis_level"] == 1
    assert body["data"]["tasks"][0]["function_code"] == "REPORT_CREATE"
    assert body["debug"] is None
    assert fake_analyzer.calls == [
        {
            "text": "create sales report",
            "user_id": "user-001",
            "conversation_id": "conversation-001",
        },
    ]


def test_analyze_endpoint_returns_debug_when_enabled() -> None:
    fake_analyzer = FakeIntentAnalyzer(make_task_list())
    app.dependency_overrides[get_intent_analyzer] = lambda: fake_analyzer

    response = client.post(
        "/api/v1/intent/analyze",
        params={"debug": True},
        json={
            "text": "create sales report",
            "user_id": "user-001",
            "conversation_id": "conversation-001",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["debug"]["level1_result"]["tasks"][0]["function_code"] == "REPORT_CREATE"
    assert body["debug"]["level2_result"] is None
    assert body["debug"]["level3_result"] is None
    assert body["debug"]["final_tasklist"]["request_id"] == "record-001"


def test_analyze_endpoint_accepts_history_and_resolves_followup() -> None:
    fake_analyzer = FakeIntentAnalyzer(make_task_list())
    app.dependency_overrides[get_intent_analyzer] = lambda: fake_analyzer

    response = client.post(
        "/api/v1/intent/analyze",
        params={"debug": True},
        json={
            "text": "继续",
            "conversation_id": "conversation-001",
            "history": [
                {"role": "user", "content": "帮我分析销售数据"},
                {"role": "assistant", "content": "已识别销售分析任务"},
            ],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert fake_analyzer.calls[0]["text"] == "继续分析销售数据"
    assert fake_analyzer.calls[0]["user_id"] == "anonymous"
    assert body["debug"]["conversation_understanding"]["resolved_references"][0]["resolved_to"] == "销售数据"


def test_analyze_endpoint_uses_server_state_when_history_is_omitted() -> None:
    fake_analyzer = FakeIntentAnalyzer(make_task_list())
    app.dependency_overrides[get_intent_analyzer] = lambda: fake_analyzer

    first = client.post(
        "/api/v1/intent/analyze",
        json={
            "text": "帮我分析销售数据",
            "user_id": "user-001",
            "conversation_id": "stateful-conversation",
        },
    )
    second = client.post(
        "/api/v1/intent/analyze",
        params={"debug": True},
        json={
            "text": "继续",
            "user_id": "user-001",
            "conversation_id": "stateful-conversation",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert fake_analyzer.calls[-1]["text"] == "继续分析销售数据"
    assert second.json()["debug"]["conversation_state"]["stored_history_count"] == 1


def test_clarification_answer_endpoint_recovers_original_task() -> None:
    analyzer = StandardIntentAnalyzer(
        registry=FunctionRegistryCatalog(),
        semantic_matcher=None,
        llm_analyzer=None,
        intent_record_service=None,
    )
    manager = ClarificationSessionManager()
    app.dependency_overrides[get_intent_analyzer] = lambda: analyzer
    app.dependency_overrides[get_clarification_session_manager] = lambda: manager

    first = client.post(
        "/api/v1/intent/analyze",
        json={
            "text": "计算销售提成",
            "user_id": "user-001",
            "conversation_id": "clarification-api-001",
        },
    )
    first_body = first.json()
    task = first_body["data"]["tasks"][0]

    assert first.status_code == 200
    assert task["status"] == "needs_clarification"
    assert task["clarification_session_id"]

    second = client.post(
        "/api/v1/intent/clarification/answer",
        json={
            "clarification_session_id": task["clarification_session_id"],
            "answer": "使用2026规则，华东区域，ERP数据",
        },
    )
    second_body = second.json()

    assert second.status_code == 200
    assert second_body["task_id"] == task["task_id"]
    assert second_body["status"] == "ready"
    assert second_body["missing_inputs"] == []
    assert second_body["final_inputs"] == {
        "calculation_policy": "2026规则",
        "data_source": "ERP",
        "data_scope": "华东区域",
    }


def test_analyze_endpoint_returns_need_confirmation_error_shape() -> None:
    fake_analyzer = FakeIntentAnalyzer(
        NeedConfirmationResult(
            reason="invalid_task_list_json",
            raw_response="not json",
        ),
    )
    app.dependency_overrides[get_intent_analyzer] = lambda: fake_analyzer

    response = client.post(
        "/api/v1/intent/analyze",
        json={
            "text": "complex unclear request",
            "user_id": "user-001",
            "conversation_id": "conversation-001",
            "debug": True,
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "need_confirmation"
    assert body["error"]["message"] == "invalid_task_list_json"
    assert body["error"]["details"]["need_confirmation"] is True
    assert body["debug"]["level3_result"]["need_confirmation"] is True
    assert body["debug"]["final_tasklist"] is None


def test_analyze_endpoint_returns_unified_error_response_for_runtime_failure() -> None:
    fake_analyzer = FakeIntentAnalyzer(RuntimeError("model gateway unavailable"))
    app.dependency_overrides[get_intent_analyzer] = lambda: fake_analyzer

    response = client.post(
        "/api/v1/intent/analyze",
        json={
            "text": "create sales report",
            "user_id": "user-001",
            "conversation_id": "conversation-001",
        },
    )

    body = response.json()
    assert response.status_code == 500
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "intent_analysis_failed"
    assert body["error"]["message"] == "model gateway unavailable"
    assert body["debug"] is None


def test_history_endpoint_returns_intent_records() -> None:
    fake_service = FakeIntentRecordService([make_record("record-001"), make_record("record-002")])
    app.dependency_overrides[get_intent_record_service] = lambda: fake_service

    response = client.get(
        "/api/v1/intent/history",
        params={
            "user_id": "user-001",
            "analysis_level": 1,
            "limit": 2,
            "offset": 0,
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["count"] == 2
    assert body["data"]["limit"] == 2
    assert body["data"]["offset"] == 0
    assert body["data"]["records"][0]["id"] == "record-001"
    assert body["data"]["records"][0]["matched_function"] == "REPORT_CREATE"
    assert fake_service.calls == [
        {
            "user_id": "user-001",
            "analysis_level": "1",
            "limit": 2,
            "offset": 0,
        },
    ]


def test_history_endpoint_returns_unified_error_response_for_runtime_failure() -> None:
    fake_service = FakeIntentRecordService(RuntimeError("database unavailable"))
    app.dependency_overrides[get_intent_record_service] = lambda: fake_service

    response = client.get("/api/v1/intent/history")

    body = response.json()
    assert response.status_code == 500
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "intent_history_query_failed"
    assert body["error"]["message"] == "database unavailable"
