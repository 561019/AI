from collections import Counter, defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes.intent import get_intent_analyzer
from app.main import app
from app.schemas.llm import NeedConfirmationResult
from app.schemas.task import TaskItem, TaskList

from intent_analysis_cases import CASES, E2ECase


REPORT_DIR = Path(__file__).parent / "reports"
REPORT_JSON = REPORT_DIR / "intent_analysis_e2e_report.json"
REPORT_MD = REPORT_DIR / "intent_analysis_e2e_report.md"
EXPECTED_CATEGORY_COUNTS = {
    "rule_hit": 30,
    "semantic_hit": 30,
    "complex_llm": 20,
    "missing_parameter": 10,
    "meaningless": 10,
}

client = TestClient(app)
RESULTS: list[dict[str, Any]] = []


class DeterministicE2EIntentAnalyzer:
    """Deterministic analyzer for HTTP e2e contract and reporting tests."""

    def __init__(self, cases: list[E2ECase]) -> None:
        self.cases_by_text = {case.text: case for case in cases}

    def analyze(
        self,
        *,
        text: str,
        user_id: str,
        conversation_id: str,
    ) -> TaskList | NeedConfirmationResult:
        case = self.cases_by_text[text]
        if not case.expected_success:
            return NeedConfirmationResult(
                reason="meaningless_text",
                raw_response=text,
            )

        tasks = [
            TaskItem(
                function_code=task.function_code,
                function_name=task.function_name,
                intent_category=task.intent_category,
                target_engine=task.target_engine,
                parameters=task.parameters,
                dependency=task.dependency,
                priority=task.priority,
                confidence=task.confidence,
            )
            for task in case.expected_tasks
        ]
        return TaskList(
            request_id=f"record-{case.case_id}",
            user_id=user_id,
            tasks=tasks,
            analysis_level=case.expected_level,
            overall_confidence=min((task.confidence for task in tasks), default=case.confidence),
        )

    def analyze_with_debug(
        self,
        *,
        text: str,
        user_id: str,
        conversation_id: str,
    ) -> Any:
        result = self.analyze(
            text=text,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        level = result.analysis_level if isinstance(result, TaskList) else 3
        debug = {
            "level1_result": result.model_dump(mode="json") if level == 1 and isinstance(result, TaskList) else None,
            "level2_result": result.model_dump(mode="json") if level == 2 and isinstance(result, TaskList) else None,
            "level3_result": result.model_dump(mode="json") if level == 3 else None,
            "final_tasklist": result.model_dump(mode="json") if isinstance(result, TaskList) else None,
        }
        return SimpleNamespace(result=result, debug=debug)


@pytest.fixture(scope="module", autouse=True)
def e2e_analyzer_override() -> None:
    assert len(CASES) == 100
    assert Counter(case.category for case in CASES) == EXPECTED_CATEGORY_COUNTS
    assert len({case.text for case in CASES}) == len(CASES)
    app.dependency_overrides.clear()
    app.dependency_overrides[get_intent_analyzer] = lambda: DeterministicE2EIntentAnalyzer(CASES)
    yield
    write_reports(RESULTS)
    app.dependency_overrides.clear()


@pytest.mark.parametrize("case", CASES, ids=[case.case_id for case in CASES])
def test_intent_analysis_e2e_case(case: E2ECase) -> None:
    started_at = perf_counter()
    response = client.post(
        "/api/v1/intent/analyze",
        json={
            "text": case.text,
            "user_id": "e2e-user",
            "conversation_id": f"e2e-{case.category}",
        },
    )
    elapsed_ms = round((perf_counter() - started_at) * 1000, 3)
    body = response.json()
    actual = extract_actual_result(body)
    correct = is_case_correct(case, body, actual)

    RESULTS.append(
        {
            "case_id": case.case_id,
            "category": case.category,
            "text": case.text,
            "expected_level": case.expected_level,
            "actual_level": actual["level"],
            "expected_function": case.expected_function,
            "actual_function": actual["function_code"],
            "expected_success": case.expected_success,
            "actual_success": body.get("success"),
            "confidence": actual["confidence"],
            "elapsed_ms": elapsed_ms,
            "correct": correct,
            "record_id": actual["record_id"],
            "error_code": actual["error_code"],
        },
    )

    assert response.status_code == 200
    assert correct


def extract_actual_result(body: dict[str, Any]) -> dict[str, Any]:
    if body.get("success"):
        task_list = body["data"]
        first_task = task_list["tasks"][0] if task_list["tasks"] else None
        return {
            "level": task_list["analysis_level"],
            "function_code": first_task["function_code"] if first_task else None,
            "confidence": task_list["overall_confidence"],
            "record_id": task_list["request_id"],
            "error_code": None,
            "missing_parameters": first_task["parameters"].get("missing_parameters", []) if first_task else [],
        }

    error = body.get("error") or {}
    details = error.get("details") or {}
    return {
        "level": details.get("level", 3 if error.get("code") == "need_confirmation" else None),
        "function_code": None,
        "confidence": 0,
        "record_id": None,
        "error_code": error.get("code"),
        "missing_parameters": [],
    }


def is_case_correct(case: E2ECase, body: dict[str, Any], actual: dict[str, Any]) -> bool:
    if body.get("success") != case.expected_success:
        return False

    if actual["level"] != case.expected_level:
        return False

    if actual["function_code"] != case.expected_function:
        return False

    if case.expected_error_code and actual["error_code"] != case.expected_error_code:
        return False

    if case.expected_missing_parameters:
        return actual["missing_parameters"] == case.expected_missing_parameters

    return True


def write_reports(results: list[dict[str, Any]]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    summary = build_summary(results)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "cases": results,
    }
    REPORT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    REPORT_MD.write_text(
        build_markdown_report(payload),
        encoding="utf-8",
    )


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    level_counts = Counter(result["actual_level"] for result in results)
    category_counts = Counter(result["category"] for result in results)
    category_correct = defaultdict(int)
    for result in results:
        if result["correct"]:
            category_correct[result["category"]] += 1

    return {
        "total": total,
        "level_counts": {f"level_{level}": level_counts.get(level, 0) for level in [1, 2, 3]},
        "level_ratios": {
            f"level_{level}": round(level_counts.get(level, 0) / total, 4) if total else 0
            for level in [1, 2, 3]
        },
        "category_counts": dict(category_counts),
        "category_accuracy": {
            category: round(category_correct[category] / count, 4)
            for category, count in category_counts.items()
        },
        "accuracy": round(sum(1 for result in results if result["correct"]) / total, 4) if total else 0,
        "average_elapsed_ms": round(
            sum(result["elapsed_ms"] for result in results) / total,
            3,
        )
        if total
        else 0,
    }


def build_markdown_report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Intent Analysis E2E Test Report",
        "",
        f"- Generated At: `{payload['generated_at']}`",
        f"- Total Cases: `{summary['total']}`",
        f"- Accuracy: `{summary['accuracy'] * 100:.2f}%`",
        f"- Average Elapsed: `{summary['average_elapsed_ms']} ms`",
        "",
        "## Level Ratios",
        "",
        "| Level | Count | Ratio |",
        "| --- | ---: | ---: |",
    ]
    for level in ["level_1", "level_2", "level_3"]:
        lines.append(
            f"| {level} | {summary['level_counts'][level]} | {summary['level_ratios'][level] * 100:.2f}% |",
        )

    lines.extend(
        [
            "",
            "## Category Accuracy",
            "",
            "| Category | Count | Accuracy |",
            "| --- | ---: | ---: |",
        ],
    )
    for category, count in summary["category_counts"].items():
        lines.append(
            f"| {category} | {count} | {summary['category_accuracy'][category] * 100:.2f}% |",
        )

    lines.extend(
        [
            "",
            "## Case Details",
            "",
            "| Case | Category | Expected Level | Actual Level | Expected Function | Actual Function | Correct | Elapsed ms |",
            "| --- | --- | ---: | ---: | --- | --- | --- | ---: |",
        ],
    )
    for result in payload["cases"]:
        lines.append(
            "| {case_id} | {category} | {expected_level} | {actual_level} | {expected_function} | "
            "{actual_function} | {correct} | {elapsed_ms} |".format(
                case_id=result["case_id"],
                category=result["category"],
                expected_level=result["expected_level"],
                actual_level=result["actual_level"],
                expected_function=result["expected_function"] or "-",
                actual_function=result["actual_function"] or "-",
                correct="yes" if result["correct"] else "no",
                elapsed_ms=result["elapsed_ms"],
            ),
        )

    return "\n".join(lines) + "\n"
