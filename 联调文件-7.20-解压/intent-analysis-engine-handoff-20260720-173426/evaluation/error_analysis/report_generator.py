from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DEFAULT_FAILURE_REPORT = PROJECT_ROOT / "evaluation" / "error_analysis" / "failure_report.json"

for path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evaluation.benchmark.benchmark_runner import DEFAULT_DATASET_ROOT, load_cases  # noqa: E402
from evaluation.error_analysis.failure_classifier import classify_failure  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate benchmark failure and optimization reports.")
    parser.add_argument("--benchmark-report", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--split", default="validation", choices=["train", "validation", "blind_test", "all"])
    parser.add_argument("--allow-blind-test", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_FAILURE_REPORT)
    parser.add_argument("--before-report", type=Path, default=None)
    parser.add_argument("--after-report", type=Path, default=None)
    parser.add_argument("--optimization-output", type=Path, default=None)
    parser.add_argument("--added-rule-count", type=int, default=0)
    parser.add_argument("--added-semantic-example-count", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    failure_report = generate_failure_report(
        benchmark_report_path=args.benchmark_report,
        dataset_root=args.dataset_root,
        split=args.split,
        allow_blind_test=args.allow_blind_test,
    )
    write_json(args.output, failure_report)
    print(f"Failure report written: {args.output}")
    print(f"Failed cases: {failure_report['total_failed']}")
    for error_type, count in failure_report["by_error_type"].items():
        print(f"- {error_type}: {count}")

    if args.before_report and args.after_report:
        optimization = generate_optimization_report(
            before_report_path=args.before_report,
            after_report_path=args.after_report,
            failure_report=failure_report,
            added_rule_count=args.added_rule_count,
            added_semantic_example_count=args.added_semantic_example_count,
        )
        output = args.optimization_output or args.output.with_name("optimization_report.json")
        write_json(output, optimization)
        print(f"Optimization report written: {output}")
    return 0


def generate_failure_report(
    *,
    benchmark_report_path: Path,
    dataset_root: Path = DEFAULT_DATASET_ROOT,
    split: str = "validation",
    allow_blind_test: bool = False,
) -> dict[str, Any]:
    benchmark_report = read_json(benchmark_report_path)
    cases = load_cases(
        dataset_root=dataset_root,
        dataset=None,
        split=split,
        allow_blind_test=allow_blind_test,
    )
    cases_by_id = {case["id"]: case for case in cases}
    rows = []
    by_error_type: dict[str, int] = {}

    for failed in benchmark_report.get("failed_cases", []):
        case = cases_by_id.get(failed["id"], {})
        classification = classify_failure(case, failed)
        by_error_type[classification.error_type] = by_error_type.get(classification.error_type, 0) + 1
        rows.append(
            {
                "id": failed["id"],
                "text": case.get("text") or failed.get("text") or "",
                "intent_category": case.get("intent_category") or failed.get("intent_category") or "",
                "expected_tasks": case.get("expected_tasks") or [
                    {"task_type": value}
                    for value in failed.get("expected_task_types", [])
                ],
                "expected_task_types": failed.get("expected_task_types", []),
                "actual_tasks": [
                    {"task_type": value}
                    for value in failed.get("actual_task_types", [])
                ],
                "actual_task_types": failed.get("actual_task_types", []),
                "missing_inputs": {
                    "expected": failed.get("expected_missing_inputs", []),
                    "actual": failed.get("actual_missing_inputs", []),
                },
                "forbidden_tasks": failed.get("forbidden_tasks", []),
                "forbidden_violations": failed.get("forbidden_violations", []),
                "error_type": classification.error_type,
                "confidence": classification.confidence,
                "reason": classification.reason,
                "suggested_action": classification.suggested_action,
            }
        )

    return {
        "source_report": str(benchmark_report_path),
        "split": split,
        "total_failed": len(rows),
        "by_error_type": dict(sorted(by_error_type.items())),
        "failures": rows,
    }


def generate_optimization_report(
    *,
    before_report_path: Path,
    after_report_path: Path,
    failure_report: dict[str, Any],
    added_rule_count: int,
    added_semantic_example_count: int,
) -> dict[str, Any]:
    before = read_json(before_report_path)
    after = read_json(after_report_path)
    before_failures = {item["id"]: item for item in before.get("failed_cases", [])}
    after_failures = {item["id"]: item for item in after.get("failed_cases", [])}
    before_failed_ids = set(before_failures)
    after_failed_ids = set(after_failures)
    improved_ids = sorted(before_failed_ids - after_failed_ids)
    regressed_ids = sorted(after_failed_ids - before_failed_ids)
    comparable_ids = sorted(before_failed_ids | after_failed_ids)
    task_type_improved_ids = [
        case_id
        for case_id in comparable_ids
        if _quality(after_failures.get(case_id))["f1"] > _quality(before_failures.get(case_id))["f1"]
    ]
    task_type_regressed_ids = [
        case_id
        for case_id in comparable_ids
        if _quality(after_failures.get(case_id))["f1"] < _quality(before_failures.get(case_id))["f1"]
    ]
    comparison = compare_metrics(before, after)
    rollback_required = (
        comparison["task_type_accuracy_delta"] > 0
        and (
            comparison["forbidden_task_rate_delta"] > 0
            or comparison["negation_accuracy_delta"] < 0
        )
    )
    return {
        "before_report": str(before_report_path),
        "after_report": str(after_report_path),
        "added_rule_count": added_rule_count,
        "added_semantic_examples_count": added_semantic_example_count,
        "metrics": comparison,
        "improved_cases": improved_ids,
        "regressed_cases": regressed_ids,
        "task_type_improved_cases": task_type_improved_ids,
        "task_type_regressed_cases": task_type_regressed_ids,
        "rollback_required": rollback_required,
        "final_recommendation": _recommendation(
            rollback_required=rollback_required,
            comparison=comparison,
            failure_report=failure_report,
        ),
    }


def compare_metrics(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_forbidden_rate = 1 - float(before.get("forbidden_pass_rate", 0))
    after_forbidden_rate = 1 - float(after.get("forbidden_pass_rate", 0))
    before_future = _category_metric(before, "future_scope", "forbidden_pass_rate")
    after_future = _category_metric(after, "future_scope", "forbidden_pass_rate")
    before_negation = _category_metric(before, "negation_expression", "forbidden_pass_rate")
    after_negation = _category_metric(after, "negation_expression", "forbidden_pass_rate")

    return {
        "task_type_accuracy": {
            "before": before.get("task_type_exact_accuracy", 0),
            "after": after.get("task_type_exact_accuracy", 0),
        },
        "task_type_accuracy_delta": float(after.get("task_type_exact_accuracy", 0))
        - float(before.get("task_type_exact_accuracy", 0)),
        "task_recall": {
            "before": before.get("macro_recall", 0),
            "after": after.get("macro_recall", 0),
        },
        "task_recall_delta": float(after.get("macro_recall", 0)) - float(before.get("macro_recall", 0)),
        "forbidden_task_rate": {
            "before": before_forbidden_rate,
            "after": after_forbidden_rate,
        },
        "forbidden_task_rate_delta": after_forbidden_rate - before_forbidden_rate,
        "future_scope_false_positive": {
            "before": 1 - before_future,
            "after": 1 - after_future,
        },
        "future_scope_false_positive_delta": (1 - after_future) - (1 - before_future),
        "negation_accuracy": {
            "before": before_negation,
            "after": after_negation,
        },
        "negation_accuracy_delta": after_negation - before_negation,
        "clarification_accuracy": {
            "before": before.get("clarification_accuracy", 0),
            "after": after.get("clarification_accuracy", 0),
        },
        "clarification_accuracy_delta": float(after.get("clarification_accuracy", 0))
        - float(before.get("clarification_accuracy", 0)),
    }


def _category_metric(report: dict[str, Any], category: str, metric: str) -> float:
    return float(report.get("by_intent_category", {}).get(category, {}).get(metric, 0))


def _quality(failure: dict[str, Any] | None) -> dict[str, float]:
    if failure is None:
        return {"f1": 1.0}
    return {"f1": float(failure.get("f1", 0))}


def _recommendation(
    *,
    rollback_required: bool,
    comparison: dict[str, Any],
    failure_report: dict[str, Any],
) -> str:
    if rollback_required:
        return (
            "Rollback required: task accuracy improved but forbidden task rate increased "
            "or negation accuracy declined."
        )
    if failure_report["by_error_type"].get("L2_SEMANTIC_MISS", 0) == 0:
        return (
            "Keep changes. Remaining failures are not safe L1/L2 expansion candidates; "
            "prioritize input validation, context resolution, negation/future-scope filtering, or L3/clarification."
        )
    if comparison["task_type_accuracy_delta"] > 0 and comparison["forbidden_task_rate_delta"] <= 0:
        return "Keep changes and continue with L2 examples for remaining semantic misses."
    if failure_report["by_error_type"].get("NEED_L3_OR_CLARIFICATION", 0):
        return "Do not add broad rules for remaining failures; prioritize clarification/L3 and protected false-positive handling."
    return "No clear accuracy improvement; review labels and failure classifications before adding rules."


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
