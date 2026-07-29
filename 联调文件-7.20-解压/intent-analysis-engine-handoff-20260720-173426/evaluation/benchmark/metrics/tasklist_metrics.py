from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CaseMetric:
    id: str
    text: str
    split: str
    intent_category: str
    expected_task_types: list[str]
    actual_task_types: list[str]
    expected_missing_inputs: list[str]
    actual_missing_inputs: list[str]
    required_clarification: bool
    actual_clarification: bool
    forbidden_tasks: list[str]
    forbidden_violations: list[str]
    task_type_exact: bool
    task_count_pass: bool
    clarification_pass: bool
    missing_inputs_pass: bool
    forbidden_pass: bool
    precision: float
    recall: float
    f1: float
    full_pass: bool
    partial_coverage_rate: float = 1.0
    uncovered_segment_count: int = 0
    l3_compensation_attempted: bool = False
    l3_compensation_success: bool = False

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_case_metrics(
    *,
    case_id: str,
    text: str,
    split: str,
    intent_category: str,
    expected_task_types: list[str],
    actual_task_types: list[str],
    expected_missing_inputs: list[str],
    actual_missing_inputs: list[str],
    required_clarification: bool,
    actual_clarification: bool,
    forbidden_tasks: list[str],
    actual_task_descriptions: list[str] | None = None,
    partial_coverage_rate: float | None = None,
    uncovered_segment_count: int = 0,
    l3_compensation_attempted: bool = False,
    l3_compensation_success: bool = False,
) -> CaseMetric:
    precision, recall, f1 = _multiset_prf(expected_task_types, actual_task_types)
    forbidden_violations = _forbidden_violations(
        forbidden_tasks=forbidden_tasks,
        actual_task_types=actual_task_types,
        actual_task_descriptions=actual_task_descriptions or [],
    )
    task_type_exact = actual_task_types == expected_task_types
    task_count_pass = len(actual_task_types) == len(expected_task_types)
    clarification_pass = bool(actual_clarification) == bool(required_clarification)
    missing_inputs_pass = set(actual_missing_inputs) == set(expected_missing_inputs)
    forbidden_pass = not forbidden_violations

    return CaseMetric(
        id=case_id,
        text=text,
        split=split,
        intent_category=intent_category,
        expected_task_types=expected_task_types,
        actual_task_types=actual_task_types,
        expected_missing_inputs=expected_missing_inputs,
        actual_missing_inputs=actual_missing_inputs,
        required_clarification=required_clarification,
        actual_clarification=actual_clarification,
        forbidden_tasks=forbidden_tasks,
        forbidden_violations=forbidden_violations,
        task_type_exact=task_type_exact,
        task_count_pass=task_count_pass,
        clarification_pass=clarification_pass,
        missing_inputs_pass=missing_inputs_pass,
        forbidden_pass=forbidden_pass,
        precision=precision,
        recall=recall,
        f1=f1,
        full_pass=all(
            (
                task_type_exact,
                task_count_pass,
                clarification_pass,
                missing_inputs_pass,
                forbidden_pass,
            )
        ),
        partial_coverage_rate=1.0 if partial_coverage_rate is None else partial_coverage_rate,
        uncovered_segment_count=uncovered_segment_count,
        l3_compensation_attempted=l3_compensation_attempted,
        l3_compensation_success=l3_compensation_success,
    )


def aggregate_case_metrics(metrics: list[CaseMetric]) -> dict[str, Any]:
    return {
        "total": len(metrics),
        "passed": sum(item.full_pass for item in metrics),
        "task_type_exact_accuracy": _ratio(metrics, "task_type_exact"),
        "task_count_accuracy": _ratio(metrics, "task_count_pass"),
        "clarification_accuracy": _ratio(metrics, "clarification_pass"),
        "missing_inputs_accuracy": _ratio(metrics, "missing_inputs_pass"),
        "forbidden_pass_rate": _ratio(metrics, "forbidden_pass"),
        "macro_precision": _average(metrics, "precision"),
        "macro_recall": _average(metrics, "recall"),
        "macro_f1": _average(metrics, "f1"),
        "forbidden_violation_count": sum(len(item.forbidden_violations) for item in metrics),
        "partial_coverage_rate": _average(metrics, "partial_coverage_rate"),
        "uncovered_segment_count": sum(item.uncovered_segment_count for item in metrics),
        "l3_compensation_success_rate": _compensation_success_rate(metrics),
        "by_split": _group(metrics, "split"),
        "by_intent_category": _group(metrics, "intent_category"),
        "failed_cases": [
            item.model_dump()
            for item in metrics
            if not item.full_pass
        ],
    }


def _multiset_prf(expected: list[str], actual: list[str]) -> tuple[float, float, float]:
    if not expected and not actual:
        return 1.0, 1.0, 1.0

    expected_counts = Counter(expected)
    actual_counts = Counter(actual)
    matched = sum((expected_counts & actual_counts).values())
    precision = matched / len(actual) if actual else 0.0
    recall = matched / len(expected) if expected else (1.0 if not actual else 0.0)
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    return precision, recall, f1


def _forbidden_violations(
    *,
    forbidden_tasks: list[str],
    actual_task_types: list[str],
    actual_task_descriptions: list[str],
) -> list[str]:
    if not forbidden_tasks:
        return []

    actual_text = "，".join([*actual_task_types, *actual_task_descriptions])
    violations = []
    for forbidden in forbidden_tasks:
        if forbidden in actual_task_types or forbidden in actual_text:
            violations.append(forbidden)
    return violations


def _ratio(metrics: list[CaseMetric], field: str) -> float:
    return sum(bool(getattr(item, field)) for item in metrics) / len(metrics) if metrics else 0.0


def _average(metrics: list[CaseMetric], field: str) -> float:
    return sum(float(getattr(item, field)) for item in metrics) / len(metrics) if metrics else 0.0


def _compensation_success_rate(metrics: list[CaseMetric]) -> float:
    attempted = [item for item in metrics if item.l3_compensation_attempted]
    if not attempted:
        return 0.0
    return sum(item.l3_compensation_success for item in attempted) / len(attempted)


def _group(metrics: list[CaseMetric], field: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[CaseMetric]] = {}
    for item in metrics:
        grouped.setdefault(str(getattr(item, field)), []).append(item)
    return {
        key: {
            "total": len(items),
            "passed": sum(item.full_pass for item in items),
            "task_type_exact_accuracy": _ratio(items, "task_type_exact"),
            "clarification_accuracy": _ratio(items, "clarification_pass"),
            "missing_inputs_accuracy": _ratio(items, "missing_inputs_pass"),
            "forbidden_pass_rate": _ratio(items, "forbidden_pass"),
            "macro_f1": _average(items, "f1"),
            "partial_coverage_rate": _average(items, "partial_coverage_rate"),
            "uncovered_segment_count": sum(item.uncovered_segment_count for item in items),
            "l3_compensation_success_rate": _compensation_success_rate(items),
        }
        for key, items in sorted(grouped.items())
    }
