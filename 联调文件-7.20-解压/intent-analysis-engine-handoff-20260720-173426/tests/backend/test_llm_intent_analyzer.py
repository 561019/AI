import json

import pytest

from app.schemas.llm import NeedConfirmationResult
from app.schemas.task import TaskList
from app.services.llm_engine import LLMIntentAnalyzer


class FakeModelGateway:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.chat_messages: list[list[dict[str, str]]] = []

    def embedding(self, texts: list[str]) -> list[list[float]]:
        return []

    def rerank(self, query: str, candidates: list[str | dict]) -> list[dict]:
        return []

    def chat(self, messages: list[dict[str, str]]) -> str:
        self.chat_messages.append(messages)
        return self.responses.pop(0)


def make_task(
    function_code: str,
    *,
    function_name: str | None = None,
    intent_category: str = "report_generation",
    target_engine: str = "report_engine",
    parameters: dict | None = None,
    dependency: list[str] | None = None,
    priority: int = 1,
    confidence: float = 0.9,
) -> dict:
    return {
        "function_code": function_code,
        "function_name": function_name or function_code.replace("_", " ").title(),
        "intent_category": intent_category,
        "target_engine": target_engine,
        "parameters": parameters or {},
        "dependency": dependency or [],
        "priority": priority,
        "confidence": confidence,
    }


def make_task_list_payload(
    *,
    user_id: str = "user-001",
    tasks: list[dict],
    confidence: float = 0.9,
) -> dict:
    return {
        "request_id": "llm-request-001",
        "user_id": user_id,
        "tasks": tasks,
        "analysis_level": 3,
        "overall_confidence": confidence,
        "created_at": "2026-07-09T00:00:00Z",
    }


COMPLEX_REQUEST_CASES = [
    (
        "summarize sales and create a monthly report",
        [
            make_task("DATA_SUMMARY", target_engine="data_engine", priority=1),
            make_task("REPORT_CREATE", dependency=["DATA_SUMMARY"], priority=2),
        ],
    ),
    (
        "query receivables then draft a finance note",
        [
            make_task("DATA_QUERY", intent_category="intelligent_qa", target_engine="knowledge_qa_engine", priority=1),
            make_task("CONTENT_CREATE", intent_category="content_creation", target_engine="content_engine", dependency=["DATA_QUERY"], priority=2),
        ],
    ),
    (
        "calculate commission but period is missing",
        [
            make_task(
                "CALCULATION",
                intent_category="rule_calculation",
                target_engine="rule_engine",
                parameters={"missing_parameters": ["period"]},
            ),
        ],
    ),
    (
        "organize operation status without naming source data",
        [
            make_task(
                "REPORT_CREATE",
                parameters={"missing_parameters": ["data_source"]},
            ),
        ],
    ),
    (
        "clean table data, group by product, and produce summary report",
        [
            make_task("DATA_SUMMARY", target_engine="data_engine", priority=1),
            make_task("REPORT_CREATE", dependency=["DATA_SUMMARY"], priority=2),
        ],
    ),
    (
        "answer reimbursement rule and write reply text",
        [
            make_task("KNOWLEDGE_QA", intent_category="intelligent_qa", target_engine="knowledge_qa_engine", priority=1),
            make_task("CONTENT_CREATE", intent_category="content_creation", target_engine="content_engine", dependency=["KNOWLEDGE_QA"], priority=2),
        ],
    ),
    (
        "identify image issue and create inspection note",
        [
            make_task("IMAGE_RECOGNITION", intent_category="image_recognition", target_engine="media_engine", priority=1),
            make_task("CONTENT_CREATE", intent_category="content_creation", target_engine="content_engine", dependency=["IMAGE_RECOGNITION"], priority=2),
        ],
    ),
    (
        "plan a workflow but destination is missing",
        [
            make_task(
                "WORKFLOW_AGENT",
                intent_category="workflow_agent",
                target_engine="workflow_engine",
                parameters={"missing_parameters": ["destination"]},
            ),
        ],
    ),
    (
        "prepare quarterly analysis from five companies",
        [
            make_task("DATA_SUMMARY", target_engine="data_engine", priority=1),
            make_task("REPORT_CREATE", dependency=["DATA_SUMMARY"], priority=2),
        ],
    ),
    (
        "read spreadsheet and calculate regional commission",
        [
            make_task("DOCUMENT_PARSE", intent_category="data_processing", target_engine="document_engine", priority=1),
            make_task("CALCULATION", intent_category="rule_calculation", target_engine="rule_engine", dependency=["DOCUMENT_PARSE"], priority=2),
        ],
    ),
    (
        "generate notice after checking policy question",
        [
            make_task("KNOWLEDGE_QA", intent_category="intelligent_qa", target_engine="knowledge_qa_engine", priority=1),
            make_task("CONTENT_CREATE", intent_category="content_creation", target_engine="content_engine", dependency=["KNOWLEDGE_QA"], priority=2),
        ],
    ),
    (
        "summarize this file but file is unspecified",
        [
            make_task(
                "DOCUMENT_PARSE",
                intent_category="data_processing",
                target_engine="document_engine",
                parameters={"missing_parameters": ["file"]},
            ),
        ],
    ),
    (
        "create customer follow-up report and send reminder task",
        [
            make_task("REPORT_CREATE", priority=1),
            make_task("WORKFLOW_AGENT", intent_category="workflow_agent", target_engine="workflow_engine", dependency=["REPORT_CREATE"], priority=2),
        ],
    ),
    (
        "compare product sales and write conclusion",
        [
            make_task("DATA_SUMMARY", target_engine="data_engine", priority=1),
            make_task("CONTENT_CREATE", intent_category="content_creation", target_engine="content_engine", dependency=["DATA_SUMMARY"], priority=2),
        ],
    ),
    (
        "calculate cost and explain exception reason",
        [
            make_task("CALCULATION", intent_category="rule_calculation", target_engine="rule_engine", priority=1),
            make_task("CONTENT_CREATE", intent_category="content_creation", target_engine="content_engine", dependency=["CALCULATION"], priority=2),
        ],
    ),
    (
        "extract table fields and query matching customer data",
        [
            make_task("DOCUMENT_PARSE", intent_category="data_processing", target_engine="document_engine", priority=1),
            make_task("DATA_QUERY", intent_category="intelligent_qa", target_engine="knowledge_qa_engine", dependency=["DOCUMENT_PARSE"], priority=2),
        ],
    ),
    (
        "write a report, period is missing, data source is missing",
        [
            make_task(
                "REPORT_CREATE",
                parameters={"missing_parameters": ["period", "data_source"]},
            ),
        ],
    ),
    (
        "analyze image and count result",
        [
            make_task("IMAGE_RECOGNITION", intent_category="image_recognition", target_engine="media_engine", priority=1),
            make_task("DATA_SUMMARY", target_engine="data_engine", dependency=["IMAGE_RECOGNITION"], priority=2),
        ],
    ),
    (
        "ask policy question only",
        [
            make_task("KNOWLEDGE_QA", intent_category="intelligent_qa", target_engine="knowledge_qa_engine"),
        ],
    ),
    (
        "draft announcement only",
        [
            make_task("CONTENT_CREATE", intent_category="content_creation", target_engine="content_engine"),
        ],
    ),
]


@pytest.mark.parametrize(("text", "tasks"), COMPLEX_REQUEST_CASES)
def test_llm_intent_analyzer_parses_complex_requests(text: str, tasks: list[dict]) -> None:
    payload = make_task_list_payload(tasks=tasks)
    gateway = FakeModelGateway([json.dumps(payload)])
    analyzer = LLMIntentAnalyzer(model_gateway=gateway)

    result = analyzer.analyze(text, user_id="user-001")

    assert isinstance(result, TaskList)
    assert result.analysis_level == 3
    assert result.user_id == "user-001"
    assert len(result.tasks) == len(tasks)
    assert result.tasks[0].function_code == tasks[0]["function_code"]
    assert gateway.chat_messages
    assert "TaskList JSON Schema" in gateway.chat_messages[0][0]["content"]


def test_llm_intent_analyzer_accepts_json_inside_markdown_fence() -> None:
    payload = make_task_list_payload(tasks=[make_task("REPORT_CREATE")])
    gateway = FakeModelGateway([f"```json\n{json.dumps(payload)}\n```"])
    analyzer = LLMIntentAnalyzer(model_gateway=gateway)

    result = analyzer.analyze("create report")

    assert isinstance(result, TaskList)
    assert result.tasks[0].function_code == "REPORT_CREATE"


def test_llm_intent_analyzer_repairs_invalid_json_once() -> None:
    repaired_payload = make_task_list_payload(tasks=[make_task("REPORT_CREATE")])
    gateway = FakeModelGateway([
        "not valid json",
        json.dumps(repaired_payload),
    ])
    analyzer = LLMIntentAnalyzer(model_gateway=gateway)

    result = analyzer.analyze("create report", user_id="user-001")

    assert isinstance(result, TaskList)
    assert result.tasks[0].function_code == "REPORT_CREATE"
    assert len(gateway.chat_messages) == 2
    assert "Repair the following model output" in gateway.chat_messages[1][0]["content"]


def test_llm_intent_analyzer_returns_need_confirmation_after_repair_failure() -> None:
    gateway = FakeModelGateway([
        "not valid json",
        "still not valid",
    ])
    analyzer = LLMIntentAnalyzer(model_gateway=gateway)

    result = analyzer.analyze("create report", user_id="user-001")

    assert isinstance(result, NeedConfirmationResult)
    assert result.need_confirmation is True
    assert result.reason == "invalid_task_list_json"
    assert result.raw_response == "still not valid"
    assert len(gateway.chat_messages) == 2


def test_llm_intent_analyzer_rejects_json_that_is_not_task_list_schema() -> None:
    gateway = FakeModelGateway([
        json.dumps({"message": "hello"}),
        "still not valid",
    ])
    analyzer = LLMIntentAnalyzer(model_gateway=gateway)

    result = analyzer.analyze("create report")

    assert isinstance(result, NeedConfirmationResult)
    assert result.reason == "invalid_task_list_json"
