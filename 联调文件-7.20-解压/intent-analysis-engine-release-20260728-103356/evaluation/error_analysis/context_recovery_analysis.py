from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DEFAULT_BENCHMARK_REPORT = (
    PROJECT_ROOT
    / "evaluation"
    / "benchmark"
    / "blind_test_report_context_recovery_final.json"
)
DEFAULT_ANALYSIS_OUTPUT = PROJECT_ROOT / "evaluation" / "error_analysis" / "context_recovery_analysis_report.json"
DEFAULT_DISTRIBUTION_OUTPUT = PROJECT_ROOT / "evaluation" / "error_analysis" / "context_distribution_report.json"

for path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evaluation.benchmark.benchmark_runner import DEFAULT_DATASET_ROOT, load_cases  # noqa: E402


CONTEXT_FAILURE_TYPES = (
    "CONTEXT_NOT_FOUND",
    "CONTEXT_PRIORITY_ERROR",
    "CONTEXT_MATCH_ERROR",
    "ELLIPSIS_PARSE_ERROR",
    "CONTEXT_CONFLICT_ERROR",
    "CLARIFICATION_MISSING",
)
CONTEXT_CATEGORIES = {"omitted_expression", "context_dependency"}
SOURCE_ORDER = ("conversation_context", "project_context", "user_project_context")
SOURCE_LABELS = {
    "conversation_context": "conversation",
    "project_context": "project",
    "user_project_context": "historical_projects",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze blind-test context recovery failures without turning blind cases "
            "into development rules."
        )
    )
    parser.add_argument("--benchmark-report", type=Path, default=DEFAULT_BENCHMARK_REPORT)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--split", default="blind_test", choices=["validation", "blind_test"])
    parser.add_argument("--allow-blind-test", action="store_true")
    parser.add_argument("--analysis-output", type=Path, default=DEFAULT_ANALYSIS_OUTPUT)
    parser.add_argument("--distribution-output", type=Path, default=DEFAULT_DISTRIBUTION_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    analysis, distribution = generate_context_recovery_reports(
        benchmark_report_path=args.benchmark_report,
        dataset_root=args.dataset_root,
        split=args.split,
        allow_blind_test=args.allow_blind_test,
    )
    write_json(args.analysis_output, analysis)
    write_json(args.distribution_output, distribution)
    print(f"Context recovery analysis written: {args.analysis_output}")
    print(f"Context distribution report written: {args.distribution_output}")
    print(f"Blind text policy: {analysis['blind_text_policy']}")
    print(f"Context-related pass rate: {analysis['context_related_pass_rate']:.2%}")
    print(f"Context recovery pass rate: {analysis['context_recovery_pass_rate']:.2%}")
    print("Failure distribution:")
    for failure_type, count in analysis["failure_classification_counts"].items():
        print(f"- {failure_type}: {count}")
    return 0


def generate_context_recovery_reports(
    *,
    benchmark_report_path: Path,
    dataset_root: Path = DEFAULT_DATASET_ROOT,
    split: str = "blind_test",
    allow_blind_test: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if split == "blind_test" and not allow_blind_test:
        raise SystemExit(
            "blind_test is protected. Re-run with --allow-blind-test for sealed analysis reporting only."
        )

    benchmark_report = read_json(benchmark_report_path)
    cases = load_cases(
        dataset_root=dataset_root,
        dataset=None,
        split=split,
        allow_blind_test=allow_blind_test,
    )
    failed_by_id = {
        failed["id"]: failed
        for failed in benchmark_report.get("failed_cases", [])
    }
    context_cases = [case for case in cases if is_context_related_case(case)]
    context_failures = [
        build_failure_row(case, failed_by_id[case["id"]])
        for case in context_cases
        if case["id"] in failed_by_id
    ]

    classification_counts = Counter(row["failure_type"] for row in context_failures)
    distribution = build_context_distribution_report(
        source_report=benchmark_report_path,
        split=split,
        context_cases=context_cases,
        failed_ids=set(failed_by_id),
        context_failures=context_failures,
    )
    context_dependency_total = sum(
        1 for case in context_cases if case.get("intent_category") == "context_dependency"
    )
    context_dependency_failed = sum(
        1
        for case in context_cases
        if case.get("intent_category") == "context_dependency" and case["id"] in failed_by_id
    )
    context_related_passed = len(context_cases) - len(context_failures)
    context_recovery_pass_rate = ratio(
        context_dependency_total - context_dependency_failed,
        context_dependency_total,
    )
    context_related_pass_rate = ratio(context_related_passed, len(context_cases))
    analysis = {
        "source_report": str(benchmark_report_path),
        "split": split,
        "blind_text_policy": (
            "Raw blind_test text is intentionally redacted from this report; use case_id, "
            "task labels, and abstract failure type only for optimization planning."
        ),
        "blind_case_development_policy": {
            "do_not_add_blind_case_to_validation": True,
            "do_not_add_keyword_rules_from_blind_case": True,
            "allowed_use": "aggregate failure classification and abstract validation planning only",
        },
        "total_cases": benchmark_report.get("total", len(cases)),
        "overall_full_pass": {
            "passed": benchmark_report.get("passed", 0),
            "total": benchmark_report.get("total", len(cases)),
            "rate": ratio(benchmark_report.get("passed", 0), benchmark_report.get("total", len(cases))),
        },
        "context_related_total": len(context_cases),
        "context_related_passed": context_related_passed,
        "context_related_failed": len(context_failures),
        "context_related_pass_rate": context_related_pass_rate,
        "context_recovery_pass_rate": context_recovery_pass_rate,
        "context_dependency": {
            "total": context_dependency_total,
            "passed": context_dependency_total - context_dependency_failed,
            "failed": context_dependency_failed,
            "pass_rate": context_recovery_pass_rate,
        },
        "failure_classification_counts": {
            failure_type: classification_counts.get(failure_type, 0)
            for failure_type in CONTEXT_FAILURE_TYPES
        },
        "main_problem_types": [
            failure_type
            for failure_type, _ in classification_counts.most_common(3)
        ],
        "failure_cases": context_failures,
        "validation_optimization_suggestions": validation_optimization_suggestions(classification_counts),
        "expected_metric_impact": expected_metric_impact(classification_counts),
        "next_step": (
            "Use the new abstract validation cases to verify a context resolver change, "
            "then re-run validation. Do not use blind_test again until final sealed acceptance."
        ),
    }
    return analysis, distribution


def is_context_related_case(case: dict[str, Any]) -> bool:
    return case.get("intent_category") in CONTEXT_CATEGORIES or has_context(case.get("context"))


def has_context(context: Any) -> bool:
    if not isinstance(context, dict):
        return False
    return any(context_items(context, source) for source in SOURCE_ORDER)


def context_items(context: dict[str, Any], source: str) -> list[dict[str, Any]]:
    value = context.get(source)
    return value if isinstance(value, list) else []


def build_failure_row(case: dict[str, Any], failed: dict[str, Any]) -> dict[str, Any]:
    classification_result = classify_context_recovery_failure(case, failed)
    context_summary = summarize_context(case.get("context"))
    return {
        "case_id": case["id"],
        "text_sha256_12": short_hash(case.get("text", "")),
        "text_redacted": True,
        "intent_category": case.get("intent_category", ""),
        "expected_task_types": list(case.get("expected_task_types") or failed.get("expected_task_types") or []),
        "actual_task_types": list(failed.get("actual_task_types") or []),
        "required_clarification": bool(case.get("required_clarification")),
        "actual_clarification": bool(failed.get("actual_clarification")),
        "expected_missing_inputs": list(case.get("missing_inputs") or failed.get("expected_missing_inputs") or []),
        "actual_missing_inputs": list(failed.get("actual_missing_inputs") or []),
        "context_sources": context_summary["sources"],
        "context_task_types": context_summary["task_types"],
        "ellipsis_type": detect_ellipsis_type(case.get("text", "")),
        "failure_type": classification_result["failure_type"],
        "failure_reason": classification_result["reason"],
        "suggested_optimization_direction": classification_result["suggested_optimization_direction"],
    }


def classify_context_recovery_failure(case: dict[str, Any], failed: dict[str, Any]) -> dict[str, str]:
    expected = list(case.get("expected_task_types") or failed.get("expected_task_types") or [])
    actual = list(failed.get("actual_task_types") or [])
    context = case.get("context") if isinstance(case.get("context"), dict) else {}
    expected_set = set(expected)
    actual_set = set(actual)

    if expected and not has_context(context) and case.get("intent_category") in CONTEXT_CATEGORIES:
        return classification(
            "CONTEXT_NOT_FOUND",
            "The case requires context recovery, but no usable context item is present in the provider payload.",
            "Verify Context Provider payload shape and request identifiers before changing parser rules.",
        )

    priority_error = detect_priority_error(context, expected, actual)
    if priority_error:
        return classification(
            "CONTEXT_PRIORITY_ERROR",
            priority_error,
            "Verify conversation > project > historical_projects precedence with an abstract validation case.",
        )

    if has_context_conflict(context) and expected_set != actual_set:
        return classification(
            "CONTEXT_CONFLICT_ERROR",
            "Multiple context sources or items expose conflicting task/data candidates.",
            "Add validation coverage for conflict-aware context selection and route unresolved conflicts to clarification.",
        )

    if case.get("required_clarification") and not failed.get("actual_clarification"):
        return classification(
            "CLARIFICATION_MISSING",
            "The expected outcome requires clarification, but the engine returned a non-clarifying result.",
            "Ensure insufficient context paths return clarification_required=true instead of guessing a task.",
        )

    if expected_set and not actual:
        return classification(
            "ELLIPSIS_PARSE_ERROR",
            "Context exists, but the expression did not recover a task from the recent context.",
            "Improve abstract ellipsis-family detection in validation before changing production rules.",
        )

    if expected_set != actual_set:
        return classification(
            "CONTEXT_MATCH_ERROR",
            "Context exists, but the recovered task type does not match the expected recent task.",
            "Validate that context recovery can override misleading short-expression L1/L2 matches.",
        )

    if set(case.get("missing_inputs") or []) != set(failed.get("actual_missing_inputs") or []):
        return classification(
            "CONTEXT_MATCH_ERROR",
            "The task type matched, but context-aware input validation produced incorrect missing inputs.",
            "Add abstract validation for recovered task inputs and task-level clarification fields.",
        )

    if not has_context(context) and case.get("required_clarification"):
        return classification(
            "CLARIFICATION_MISSING",
            "No sufficient context is available for an omitted request.",
            "Keep no-context omitted expressions in clarification instead of generating a task.",
        )

    return classification(
        "CONTEXT_MATCH_ERROR",
        "The case failed full-pass after context recovery checks.",
        "Inspect task-level recovery and validation with abstract validation data.",
    )


def classification(
    failure_type: str,
    reason: str,
    suggested_optimization_direction: str,
) -> dict[str, str]:
    return {
        "failure_type": failure_type,
        "reason": reason,
        "suggested_optimization_direction": suggested_optimization_direction,
    }


def detect_priority_error(context: dict[str, Any], expected: list[str], actual: list[str]) -> str | None:
    expected_set = set(expected)
    actual_set = set(actual)
    if not expected_set or expected_set == actual_set:
        return None

    source_task_types = {
        source: {str(item.get("task_type")) for item in context_items(context, source) if item.get("task_type")}
        for source in SOURCE_ORDER
    }
    expected_sources = [
        source
        for source in SOURCE_ORDER
        if expected_set & source_task_types[source]
    ]
    actual_sources = [
        source
        for source in SOURCE_ORDER
        if actual_set & source_task_types[source]
    ]
    if not expected_sources or not actual_sources:
        return None

    expected_rank = min(SOURCE_ORDER.index(source) for source in expected_sources)
    actual_rank = min(SOURCE_ORDER.index(source) for source in actual_sources)
    if actual_rank > expected_rank:
        return (
            "A lower-priority context source matched the actual task while a higher-priority "
            "source contained the expected task."
        )
    return None


def has_context_conflict(context: dict[str, Any]) -> bool:
    if not isinstance(context, dict):
        return False
    task_types_by_source = [
        {str(item.get("task_type")) for item in context_items(context, source) if item.get("task_type")}
        for source in SOURCE_ORDER
    ]
    non_empty = [values for values in task_types_by_source if values]
    if len(non_empty) >= 2 and len(set().union(*non_empty)) > 1:
        return True

    data_sources = [
        str(item.get("data_source"))
        for source in SOURCE_ORDER
        for item in context_items(context, source)
        if item.get("data_source")
    ]
    return len(set(data_sources)) > 1


def build_context_distribution_report(
    *,
    source_report: Path,
    split: str,
    context_cases: list[dict[str, Any]],
    failed_ids: set[str],
    context_failures: list[dict[str, Any]],
) -> dict[str, Any]:
    ellipsis_types: Counter[str] = Counter()
    context_sources: Counter[str] = Counter()
    task_types: Counter[str] = Counter()
    pass_fail_by_category: dict[str, Counter[str]] = {}

    for case in context_cases:
        ellipsis_types[detect_ellipsis_type(case.get("text", ""))] += 1
        context_sources[context_source_label(case.get("context"))] += 1
        for task_type in case.get("expected_task_types") or []:
            task_types[str(task_type)] += 1
        category = str(case.get("intent_category") or "unknown")
        pass_fail_by_category.setdefault(category, Counter())
        pass_fail_by_category[category]["failed" if case["id"] in failed_ids else "passed"] += 1

    failure_distribution = Counter(row["failure_type"] for row in context_failures)
    return {
        "source_report": str(source_report),
        "split": split,
        "blind_text_policy": "raw_text_redacted",
        "total_context_related_cases": len(context_cases),
        "passed": sum(1 for case in context_cases if case["id"] not in failed_ids),
        "failed": sum(1 for case in context_cases if case["id"] in failed_ids),
        "success_failure_by_intent_category": {
            category: dict(counter)
            for category, counter in sorted(pass_fail_by_category.items())
        },
        "ellipsis_types": dict(sorted(ellipsis_types.items())),
        "context_sources": dict(sorted(context_sources.items())),
        "task_types": dict(sorted(task_types.items())),
        "failure_distribution": {
            failure_type: failure_distribution.get(failure_type, 0)
            for failure_type in CONTEXT_FAILURE_TYPES
        },
    }


def summarize_context(context: Any) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {"sources": [], "task_types": []}
    sources = []
    task_types: list[str] = []
    for source in SOURCE_ORDER:
        items = context_items(context, source)
        if items:
            sources.append(SOURCE_LABELS[source])
        for item in items:
            task_type = item.get("task_type")
            if task_type and task_type not in task_types:
                task_types.append(str(task_type))
    return {"sources": sources, "task_types": task_types}


def context_source_label(context: Any) -> str:
    summary = summarize_context(context)
    sources = summary["sources"]
    if not sources:
        return "none"
    if len(sources) == 1:
        return sources[0]
    return "+".join(sources)


def detect_ellipsis_type(text: str) -> str:
    normalized = "".join(str(text).split())
    if any(token in normalized for token in ("重新", "再来", "再算", "再做", "再处理")):
        return "repeat_action"
    if any(token in normalized for token in ("再", "一遍", "一次")):
        return "repeat_or_incremental"
    if any(token in normalized for token in ("继续", "接着", "跟进")):
        return "continue_followup"
    if any(token in normalized for token in ("上一轮", "刚才", "之前", "照旧", "同样", "按原来")):
        return "explicit_previous_reference"
    if any(token in normalized for token in ("也", "换成", "另一个")):
        return "also_or_variant"
    if any(token in normalized for token in ("维度", "方式", "口径")):
        return "dimension_or_method_change"
    if any(token in normalized for token in ("这个", "那个", "它", "结果")):
        return "pronoun_reference"
    return "unknown_or_generic_ellipsis"


def validation_optimization_suggestions(classification_counts: Counter[str]) -> list[dict[str, Any]]:
    suggestions = []
    if classification_counts["ELLIPSIS_PARSE_ERROR"]:
        suggestions.append(
            {
                "failure_type": "ELLIPSIS_PARSE_ERROR",
                "abstract_validation_case": "Generic continue/repeat expression with valid recent conversation task.",
                "expected_behavior": "Bind to the nearest related task; preserve task_id/task_type.",
                "development_constraint": "Do not add single blind phrase keywords.",
            }
        )
    if classification_counts["CONTEXT_MATCH_ERROR"]:
        suggestions.append(
            {
                "failure_type": "CONTEXT_MATCH_ERROR",
                "abstract_validation_case": (
                    "Short follow-up text has its own weak L1/L2 interpretation, but recent context "
                    "contains a stronger task identity."
                ),
                "expected_behavior": "Use recent context task identity before accepting misleading standalone match.",
                "development_constraint": "Validate by task-family behavior, not by blind case wording.",
            }
        )
    if classification_counts["CONTEXT_PRIORITY_ERROR"]:
        suggestions.append(
            {
                "failure_type": "CONTEXT_PRIORITY_ERROR",
                "abstract_validation_case": "Conversation context conflicts with project/history context.",
                "expected_behavior": "conversation > project > historical_projects.",
                "development_constraint": "Do not change Context Provider ownership.",
            }
        )
    if classification_counts["CLARIFICATION_MISSING"]:
        suggestions.append(
            {
                "failure_type": "CLARIFICATION_MISSING",
                "abstract_validation_case": "Omitted expression without usable context.",
                "expected_behavior": "Return clarification_required=true and no guessed task.",
                "development_constraint": "Do not synthesize tasks solely from historical context.",
            }
        )
    if not suggestions:
        suggestions.append(
            {
                "failure_type": "NONE_DOMINANT",
                "abstract_validation_case": "Maintain current coverage and monitor sealed blind acceptance.",
                "expected_behavior": "No rule change needed from blind analysis alone.",
                "development_constraint": "Keep blind_test sealed.",
            }
        )
    return suggestions


def expected_metric_impact(classification_counts: Counter[str]) -> dict[str, str]:
    impacts = {
        "context_recovery_accuracy": "Expected to improve after validation-driven context matching changes.",
        "false_positive_rate": "Should remain flat; no positive L1/L2 expansion is proposed.",
        "clarification_accuracy": "May improve if no-context omitted expressions stay in clarification.",
    }
    if classification_counts["CONTEXT_MATCH_ERROR"]:
        impacts["task_type_exact_accuracy"] = (
            "Expected to improve on context_dependency and omitted_expression without broad task recall expansion."
        )
    if classification_counts["CLARIFICATION_MISSING"]:
        impacts["clarification_decision_accuracy"] = (
            "Expected to improve for insufficient-context follow-ups."
        )
    return impacts


def short_hash(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]


def ratio(left: Any, right: Any) -> float:
    denominator = float(right or 0)
    if denominator == 0:
        return 0.0
    return float(left or 0) / denominator


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
