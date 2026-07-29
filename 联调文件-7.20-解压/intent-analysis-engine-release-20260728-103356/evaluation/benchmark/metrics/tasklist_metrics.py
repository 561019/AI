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
    expected_clarification_questions: list[str] | None
    actual_clarification_questions: list[str]
    extra_clarification_questions: list[str]
    clarification_decision_pass: bool
    clarification_field_pass: bool
    clarification_question_pass: bool
    unnecessary_clarification_question_pass: bool
    max_extra_clarification_questions: int | None
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
    missing_input_precision: float = 1.0
    missing_input_recall: float = 1.0
    over_clarification: bool = False
    partial_coverage_rate: float = 1.0
    uncovered_segment_count: int = 0
    l3_compensation_attempted: bool = False
    l3_compensation_success: bool = False
    expected_conflict_types: list[str] | None = None
    actual_conflict_types: list[str] | None = None
    actual_conflicts: list[dict[str, Any]] | None = None
    expected_conflict_clarification: bool | None = None
    actual_conflict_clarification: bool = False
    false_resolutions: list[str] | None = None
    conflict_detection_pass: bool = True
    conflict_clarification_pass: bool = True
    false_resolution_pass: bool = True
    clarification_recovery_attempted: bool = False
    clarification_recovery_pass: bool = True
    clarification_recovery: dict[str, Any] | None = None

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
    expected_clarification_questions: list[str] | None = None,
    actual_clarification_questions: list[str] | None = None,
    max_extra_clarification_questions: int | None = None,
    forbidden_tasks: list[str],
    actual_task_descriptions: list[str] | None = None,
    partial_coverage_rate: float | None = None,
    uncovered_segment_count: int = 0,
    l3_compensation_attempted: bool = False,
    l3_compensation_success: bool = False,
    expected_conflict_types: list[str] | None = None,
    actual_conflict_types: list[str] | None = None,
    actual_conflicts: list[dict[str, Any]] | None = None,
    expected_conflict_clarification: bool | None = None,
    clarification_recovery: dict[str, Any] | None = None,
) -> CaseMetric:
    precision, recall, f1 = _multiset_prf(expected_task_types, actual_task_types)
    expected_conflict_types = expected_conflict_types or []
    actual_conflict_types = actual_conflict_types or []
    actual_conflicts = actual_conflicts or []
    actual_clarification_questions = actual_clarification_questions or []
    clarification_recovery = clarification_recovery or {
        "attempted": False,
        "passed": True,
    }
    forbidden_violations = _forbidden_violations(
        forbidden_tasks=forbidden_tasks,
        actual_task_types=actual_task_types,
        actual_task_descriptions=actual_task_descriptions or [],
    )
    task_type_exact = actual_task_types == expected_task_types
    task_count_pass = len(actual_task_types) == len(expected_task_types)
    clarification_decision_pass = bool(actual_clarification) == bool(required_clarification)
    clarification_pass = clarification_decision_pass
    clarification_field_pass = set(actual_missing_inputs) == set(expected_missing_inputs)
    missing_inputs_pass = clarification_field_pass
    missing_input_precision, missing_input_recall, _ = _multiset_prf(
        expected_missing_inputs,
        actual_missing_inputs,
    )
    over_clarification = bool(actual_clarification and not required_clarification)
    clarification_question_pass = _clarification_question_pass(
        expected=expected_clarification_questions,
        actual=actual_clarification_questions,
    )
    extra_clarification_questions = _extra_clarification_questions(
        expected=expected_clarification_questions,
        actual=actual_clarification_questions,
        required_clarification=required_clarification,
    )
    unnecessary_clarification_question_pass = _unnecessary_question_pass(
        extra_questions=extra_clarification_questions,
        max_extra=max_extra_clarification_questions,
        expected=expected_clarification_questions,
        required_clarification=required_clarification,
    )
    forbidden_pass = not forbidden_violations
    conflict_detection_pass = set(actual_conflict_types) == set(expected_conflict_types)
    actual_conflict_clarification = any(
        conflict.get("resolution_status") == "needs_clarification"
        for conflict in actual_conflicts
    )
    conflict_clarification_pass = (
        True
        if expected_conflict_clarification is None
        else bool(actual_conflict_clarification) == bool(expected_conflict_clarification)
    )
    false_resolutions = _false_resolutions(
        expected_conflict_types=expected_conflict_types,
        expected_conflict_clarification=expected_conflict_clarification,
        actual_conflicts=actual_conflicts,
    )
    false_resolution_pass = not false_resolutions

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
        expected_clarification_questions=expected_clarification_questions,
        actual_clarification_questions=actual_clarification_questions,
        extra_clarification_questions=extra_clarification_questions,
        clarification_decision_pass=clarification_decision_pass,
        clarification_field_pass=clarification_field_pass,
        clarification_question_pass=clarification_question_pass,
        unnecessary_clarification_question_pass=unnecessary_clarification_question_pass,
        max_extra_clarification_questions=max_extra_clarification_questions,
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
                clarification_question_pass,
                unnecessary_clarification_question_pass,
                forbidden_pass,
                conflict_detection_pass,
                conflict_clarification_pass,
                false_resolution_pass,
                bool(clarification_recovery.get("passed", True)),
            )
        ),
        missing_input_precision=missing_input_precision,
        missing_input_recall=missing_input_recall,
        over_clarification=over_clarification,
        partial_coverage_rate=1.0 if partial_coverage_rate is None else partial_coverage_rate,
        uncovered_segment_count=uncovered_segment_count,
        l3_compensation_attempted=l3_compensation_attempted,
        l3_compensation_success=l3_compensation_success,
        expected_conflict_types=expected_conflict_types,
        actual_conflict_types=actual_conflict_types,
        actual_conflicts=actual_conflicts,
        expected_conflict_clarification=expected_conflict_clarification,
        actual_conflict_clarification=actual_conflict_clarification,
        false_resolutions=false_resolutions,
        conflict_detection_pass=conflict_detection_pass,
        conflict_clarification_pass=conflict_clarification_pass,
        false_resolution_pass=false_resolution_pass,
        clarification_recovery_attempted=bool(clarification_recovery.get("attempted", False)),
        clarification_recovery_pass=bool(clarification_recovery.get("passed", True)),
        clarification_recovery=clarification_recovery,
    )


def aggregate_case_metrics(metrics: list[CaseMetric]) -> dict[str, Any]:
    return {
        "total": len(metrics),
        "passed": sum(item.full_pass for item in metrics),
        "task_type_exact_accuracy": _ratio(metrics, "task_type_exact"),
        "task_count_accuracy": _ratio(metrics, "task_count_pass"),
        "clarification_accuracy": _ratio(metrics, "clarification_pass"),
        "clarification_decision_accuracy": _ratio(metrics, "clarification_decision_pass"),
        "clarification_field_accuracy": _ratio(metrics, "clarification_field_pass"),
        "clarification_question_accuracy": _scoped_ratio(
            metrics,
            "clarification_question_pass",
            lambda item: item.expected_clarification_questions is not None,
        ),
        "no_unnecessary_clarification_question_accuracy": _scoped_ratio(
            metrics,
            "unnecessary_clarification_question_pass",
            lambda item: item.expected_clarification_questions is not None or not item.required_clarification,
        ),
        "unnecessary_clarification_question_rate": 1
        - _scoped_ratio(
            metrics,
            "unnecessary_clarification_question_pass",
            lambda item: item.expected_clarification_questions is not None or not item.required_clarification,
        ),
        "clarification_recovery_accuracy": _scoped_ratio(
            metrics,
            "clarification_recovery_pass",
            lambda item: item.clarification_recovery_attempted,
        ),
        "context_recovery_accuracy": _context_recovery_accuracy(metrics),
        "missing_inputs_accuracy": _ratio(metrics, "missing_inputs_pass"),
        "missing_input_precision": _average(metrics, "missing_input_precision"),
        "missing_input_recall": _average(metrics, "missing_input_recall"),
        "over_clarification_rate": _ratio(metrics, "over_clarification"),
        "forbidden_pass_rate": _ratio(metrics, "forbidden_pass"),
        "false_positive_rate": _forbidden_violation_rate(metrics),
        "future_scope_false_positive_rate": _category_forbidden_violation_rate(metrics, "future_scope"),
        "negation_false_positive_rate": _category_forbidden_violation_rate(metrics, "negation_expression"),
        "macro_precision": _average(metrics, "precision"),
        "macro_recall": _average(metrics, "recall"),
        "macro_f1": _average(metrics, "f1"),
        "forbidden_violation_count": sum(len(item.forbidden_violations) for item in metrics),
        "partial_coverage_rate": _average(metrics, "partial_coverage_rate"),
        "uncovered_segment_count": sum(item.uncovered_segment_count for item in metrics),
        "l3_compensation_success_rate": _compensation_success_rate(metrics),
        "conflict_detection_accuracy": _ratio(metrics, "conflict_detection_pass"),
        "conflict_clarification_accuracy": _ratio(metrics, "conflict_clarification_pass"),
        "false_resolution_rate": _false_resolution_rate(metrics),
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


def _false_resolutions(
    *,
    expected_conflict_types: list[str],
    expected_conflict_clarification: bool | None,
    actual_conflicts: list[dict[str, Any]],
) -> list[str]:
    if expected_conflict_clarification is not True:
        return []
    false_resolutions: list[str] = []
    for conflict_type in expected_conflict_types:
        matching = [
            conflict
            for conflict in actual_conflicts
            if conflict.get("conflict_type") == conflict_type
        ]
        if matching and not any(
            conflict.get("resolution_status") == "needs_clarification"
            for conflict in matching
        ):
            false_resolutions.append(conflict_type)
    return false_resolutions


def _clarification_question_pass(
    *,
    expected: list[str] | None,
    actual: list[str],
) -> bool:
    if expected is None:
        return True
    return set(expected).issubset(set(actual))


def _extra_clarification_questions(
    *,
    expected: list[str] | None,
    actual: list[str],
    required_clarification: bool,
) -> list[str]:
    if expected is not None:
        expected_set = set(expected)
        return [question for question in actual if question not in expected_set]
    if not required_clarification:
        return list(actual)
    return []


def _unnecessary_question_pass(
    *,
    extra_questions: list[str],
    max_extra: int | None,
    expected: list[str] | None,
    required_clarification: bool,
) -> bool:
    if expected is None and required_clarification:
        return True
    limit = 0 if max_extra is None else max_extra
    return len(extra_questions) <= limit


def _ratio(metrics: list[CaseMetric], field: str) -> float:
    return sum(bool(getattr(item, field)) for item in metrics) / len(metrics) if metrics else 0.0


def _scoped_ratio(
    metrics: list[CaseMetric],
    field: str,
    applies: Any,
) -> float:
    scoped = [item for item in metrics if applies(item)]
    if not scoped:
        return 0.0
    return _ratio(scoped, field)


def _average(metrics: list[CaseMetric], field: str) -> float:
    return sum(float(getattr(item, field)) for item in metrics) / len(metrics) if metrics else 0.0


def _compensation_success_rate(metrics: list[CaseMetric]) -> float:
    attempted = [item for item in metrics if item.l3_compensation_attempted]
    if not attempted:
        return 0.0
    return sum(item.l3_compensation_success for item in attempted) / len(attempted)


def _false_resolution_rate(metrics: list[CaseMetric]) -> float:
    conflict_cases = [
        item
        for item in metrics
        if item.expected_conflict_types
    ]
    if not conflict_cases:
        return 0.0
    return sum(not item.false_resolution_pass for item in conflict_cases) / len(conflict_cases)


def _context_recovery_accuracy(metrics: list[CaseMetric]) -> float:
    context_cases = [item for item in metrics if item.intent_category == "context_dependency"]
    if not context_cases:
        return 0.0
    return _ratio(context_cases, "full_pass")


def _forbidden_violation_rate(metrics: list[CaseMetric]) -> float:
    scoped = [item for item in metrics if item.forbidden_tasks]
    if not scoped:
        return 0.0
    return sum(not item.forbidden_pass for item in scoped) / len(scoped)


def _category_forbidden_violation_rate(metrics: list[CaseMetric], category: str) -> float:
    return _forbidden_violation_rate([item for item in metrics if item.intent_category == category])


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
            "clarification_decision_accuracy": _ratio(items, "clarification_decision_pass"),
            "clarification_field_accuracy": _ratio(items, "clarification_field_pass"),
            "clarification_question_accuracy": _scoped_ratio(
                items,
                "clarification_question_pass",
                lambda item: item.expected_clarification_questions is not None,
            ),
            "no_unnecessary_clarification_question_accuracy": _scoped_ratio(
                items,
                "unnecessary_clarification_question_pass",
                lambda item: item.expected_clarification_questions is not None or not item.required_clarification,
            ),
            "clarification_recovery_accuracy": _scoped_ratio(
                items,
                "clarification_recovery_pass",
                lambda item: item.clarification_recovery_attempted,
            ),
            "context_recovery_accuracy": _context_recovery_accuracy(items),
            "missing_inputs_accuracy": _ratio(items, "missing_inputs_pass"),
            "missing_input_precision": _average(items, "missing_input_precision"),
            "missing_input_recall": _average(items, "missing_input_recall"),
            "over_clarification_rate": _ratio(items, "over_clarification"),
            "forbidden_pass_rate": _ratio(items, "forbidden_pass"),
            "forbidden_false_positive_rate": _forbidden_violation_rate(items),
            "macro_f1": _average(items, "f1"),
            "partial_coverage_rate": _average(items, "partial_coverage_rate"),
            "uncovered_segment_count": sum(item.uncovered_segment_count for item in items),
            "l3_compensation_success_rate": _compensation_success_rate(items),
            "conflict_detection_accuracy": _ratio(items, "conflict_detection_pass"),
            "conflict_clarification_accuracy": _ratio(items, "conflict_clarification_pass"),
            "false_resolution_rate": _false_resolution_rate(items),
        }
        for key, items in sorted(grouped.items())
    }
