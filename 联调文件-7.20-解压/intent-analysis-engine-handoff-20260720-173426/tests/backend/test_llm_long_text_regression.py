import json
import os
from pathlib import Path
from typing import Any

from app.schemas.intent_analysis import IntentAnalysisResult, TaskItem
from app.services.intent_analysis_engine import FunctionRegistryCatalog
from app.services.intent_analysis_engine.llm import LLMTaskAnalyzer
from app.services.model_gateway import ModelGateway


CASE_PATH = (
    Path(__file__).resolve().parents[2]
    / "evaluation"
    / "llm_regression"
    / "sales_operation_analysis_case.json"
)


class FakeGateway:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def analyze(self, messages, response_schema=None):
        class Response:
            def __init__(self, payload: dict[str, Any]) -> None:
                self.content = json.dumps(payload, ensure_ascii=False)

        return Response(self.response)


def load_case() -> dict[str, Any]:
    return json.loads(CASE_PATH.read_text(encoding="utf-8"))


def run_llm_case(case: dict[str, Any], *, live: bool = False) -> IntentAnalysisResult:
    gateway = ModelGateway(timeout=120) if live else FakeGateway(case["mock_llm_response"])
    outcome = LLMTaskAnalyzer(
        model_gateway=gateway,
        registry=FunctionRegistryCatalog(),
    ).analyze_with_validation(case["text"], user_id="llm-regression")

    assert outcome.rejection_reasons == []
    assert outcome.result is not None
    return outcome.result


def test_sales_operation_analysis_llm_regression_metrics_with_contract_guard() -> None:
    case = load_case()
    result = run_llm_case(case)
    metrics = evaluate_case(case, result)

    assert metrics == {
        "task_count": 5,
        "missing_task_count": 0,
        "erroneous_task_count": 0,
        "clarification_correct": True,
        "dependencies_correct": True,
    }


def test_sales_operation_analysis_llm_case_schema_is_complete() -> None:
    case = load_case()

    assert case["text"].strip()
    assert case["expected"]["task_count"] == 5
    assert [task["name"] for task in case["expected"]["required_tasks"]] == [
        "整理销售数据",
        "分析销售表现",
        "分析销售下降原因",
        "计算销售人员奖金和提成",
        "生成经营分析材料",
    ]
    assert case["expected"]["forbidden_task_keywords"] == [
        "智能化平台开发",
        "异常监控",
        "主动提醒",
        "自动发送邮件",
        "正式PPT",
        "三年历史数据治理",
    ]
    assert {topic["name"] for topic in case["expected"]["required_clarification_topics"]} == {
        "提成规则版本",
        "计算范围",
        "数据来源",
        "时间范围",
    }


def test_sales_operation_analysis_live_llm_regression_when_enabled() -> None:
    if os.environ.get("RUN_LIVE_LLM_REGRESSION") != "1":
        return

    case = load_case()
    result = run_llm_case(case, live=True)
    metrics = evaluate_case(case, result)

    assert metrics["task_count"] == 5
    assert metrics["missing_task_count"] == 0
    assert metrics["erroneous_task_count"] == 0
    assert metrics["clarification_correct"] is True
    assert metrics["dependencies_correct"] is True


def evaluate_case(case: dict[str, Any], result: IntentAnalysisResult) -> dict[str, Any]:
    expected = case["expected"]
    matched_task_ids = _match_required_tasks(expected["required_tasks"], result.tasks)
    forbidden_count = _count_forbidden_tasks(expected["forbidden_task_keywords"], result.tasks)
    extra_count = sum(
        1
        for task in result.tasks
        if task.task_id not in set(matched_task_ids.values())
    )

    return {
        "task_count": len(result.tasks),
        "missing_task_count": len(expected["required_tasks"]) - len(matched_task_ids),
        "erroneous_task_count": forbidden_count + extra_count,
        "clarification_correct": _clarification_correct(
            expected["required_clarification_topics"],
            result,
        ),
        "dependencies_correct": _dependencies_correct(
            expected["dependency_rules"],
            result.tasks,
            matched_task_ids,
        ),
    }


def _match_required_tasks(
    expected_tasks: list[dict[str, Any]],
    actual_tasks: list[TaskItem],
) -> dict[str, str]:
    matched: dict[str, str] = {}
    used_ids: set[str] = set()

    for expected in expected_tasks:
        for task in actual_tasks:
            if task.task_id in used_ids:
                continue
            if _task_matches(expected, task):
                matched[expected["name"]] = task.task_id
                used_ids.add(task.task_id)
                break
    return matched


def _task_matches(expected: dict[str, Any], task: TaskItem) -> bool:
    allowed_types = set(expected.get("allowed_task_types") or [expected.get("task_type")])
    return all(
        [
            task.task_description == expected["name"],
            task.task_type in allowed_types,
            task.action == expected["action"],
            all(keyword in task.object for keyword in expected["object_keywords"]),
        ]
    )


def _count_forbidden_tasks(forbidden_keywords: list[str], actual_tasks: list[TaskItem]) -> int:
    count = 0
    for task in actual_tasks:
        text = f"{task.task_type} {task.task_description} {task.object}"
        if any(keyword in text for keyword in forbidden_keywords):
            count += 1
    return count


def _clarification_correct(
    expected_topics: list[dict[str, Any]],
    result: IntentAnalysisResult,
) -> bool:
    if not result.clarification_required:
        return False
    questions = result.clarification_questions
    return all(
        any(all(keyword in question for keyword in topic["keywords"]) for question in questions)
        for topic in expected_topics
    )


def _dependencies_correct(
    dependency_rules: list[dict[str, Any]],
    actual_tasks: list[TaskItem],
    matched_task_ids: dict[str, str],
) -> bool:
    tasks_by_id = {task.task_id: task for task in actual_tasks}
    for rule in dependency_rules:
        task_id = matched_task_ids.get(rule["task"])
        if not task_id:
            return False
        task = tasks_by_id[task_id]
        for dependency_name in rule["depends_on"]:
            dependency_id = matched_task_ids.get(dependency_name)
            if not dependency_id or dependency_id not in task.dependencies:
                return False
    return True
