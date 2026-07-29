from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.services.intent_analysis_engine.task_schema import TaskTypeSchemaCatalog


ErrorType = Literal[
    "L1_RULE_MISS",
    "L2_SEMANTIC_MISS",
    "NEED_L3_OR_CLARIFICATION",
    "UNNECESSARY_REQUIRED_INPUT",
    "MISSING_SCHEMA_FIELD",
    "WRONG_OPTIONAL_REQUIRED",
]


@dataclass(frozen=True)
class FailureClassification:
    error_type: ErrorType
    confidence: str
    reason: str
    suggested_action: str

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


L1_CATEGORIES = {"short_instruction"}
L2_CATEGORIES = {
    "colloquial_expression",
    "omitted_expression",
    "context_dependency",
}
CLARIFICATION_CATEGORIES = {
    "ambiguous_request",
    "insufficient_information",
}
PROTECTED_CATEGORIES = {
    "future_scope",
    "negation_expression",
}


def classify_failure(case: dict[str, Any], failed_metric: dict[str, Any]) -> FailureClassification:
    """Classify benchmark failures into optimization-safe buckets.

    This classifier intentionally uses benchmark labels and observed failure
    shape. It does not decide new rules from free-form intuition.
    """

    category = str(case.get("intent_category") or failed_metric.get("intent_category") or "")
    expected = list(case.get("expected_task_types") or failed_metric.get("expected_task_types") or [])
    actual = list(failed_metric.get("actual_task_types") or [])
    forbidden_violations = list(failed_metric.get("forbidden_violations") or [])
    required_clarification = bool(case.get("required_clarification", failed_metric.get("required_clarification")))
    task_type_exact = bool(failed_metric.get("task_type_exact", actual == expected))
    expected_missing_inputs = list(
        case.get("missing_inputs")
        or failed_metric.get("expected_missing_inputs")
        or []
    )
    actual_missing_inputs = list(failed_metric.get("actual_missing_inputs") or [])

    if category in PROTECTED_CATEGORIES or forbidden_violations:
        return FailureClassification(
            error_type="NEED_L3_OR_CLARIFICATION",
            confidence="high",
            reason=(
                "Failure is in a protected negation/future-scope category or produced a forbidden task. "
                "Do not expand L1/L2 positive recognition for this case."
            ),
            suggested_action="Improve exclusion/negation filtering or keep as clarification/L3; do not add positive rule.",
        )

    if task_type_exact:
        schema_failure = _classify_schema_failure(
            expected_task_types=expected,
            expected_missing_inputs=expected_missing_inputs,
            actual_missing_inputs=actual_missing_inputs,
        )
        if schema_failure is not None:
            return schema_failure

    if category in CLARIFICATION_CATEGORIES or not expected or required_clarification:
        return FailureClassification(
            error_type="NEED_L3_OR_CLARIFICATION",
            confidence="high",
            reason="Case is ambiguous, information-insufficient, or expected to require clarification.",
            suggested_action="Do not add L1/L2 positive rule. Route to clarification or L3 fallback.",
        )

    if task_type_exact:
        return FailureClassification(
            error_type="NEED_L3_OR_CLARIFICATION",
            confidence="high",
            reason="Task type is already correct; failure is caused by clarification or missing-input mismatch.",
            suggested_action="Do not add semantic examples. Review input validation or benchmark labels.",
        )

    if category in {"omitted_expression", "context_dependency"} and case.get("context"):
        return FailureClassification(
            error_type="NEED_L3_OR_CLARIFICATION",
            confidence="high",
            reason="Failure depends on explicit context; broad L1/L2 expansion could create standalone false positives.",
            suggested_action="Improve context resolution or route to L3/clarification; do not add broad semantic example.",
        )

    if category in L1_CATEGORIES and not actual:
        return FailureClassification(
            error_type="L1_RULE_MISS",
            confidence="high",
            reason="High-certainty short instruction produced no task.",
            suggested_action="Add a narrow L1 rule only for this exact deterministic expression family.",
        )

    if category in L1_CATEGORIES and set(expected).issubset(set(actual)) and len(actual) > len(expected):
        return FailureClassification(
            error_type="NEED_L3_OR_CLARIFICATION",
            confidence="medium",
            reason="Expected task was found but extra tasks were produced.",
            suggested_action="Do not add positive L1 rule. Review decomposition or benchmark label before changing rules.",
        )

    if category in L1_CATEGORIES:
        return FailureClassification(
            error_type="L1_RULE_MISS",
            confidence="medium",
            reason="High-certainty short instruction mapped to the wrong task type.",
            suggested_action="Add or tighten a narrow L1 rule if the benchmark text is deterministic.",
        )

    if category in L2_CATEGORIES:
        return FailureClassification(
            error_type="L2_SEMANTIC_MISS",
            confidence="high",
            reason="Synonym, colloquial, omitted, or context-dependent expression did not match expected task type.",
            suggested_action="Add semantic examples/business synonyms or context resolver coverage; avoid broad L1 keywords.",
        )

    if expected and not actual:
        return FailureClassification(
            error_type="L2_SEMANTIC_MISS",
            confidence="medium",
            reason="Expected task types were not recalled and case is not protected.",
            suggested_action="Prefer semantic examples before adding L1 rules.",
        )

    return FailureClassification(
        error_type="NEED_L3_OR_CLARIFICATION",
        confidence="medium",
        reason="Failure is not a safe L1/L2 expansion candidate.",
        suggested_action="Review with L3/clarification or data labeling; do not add rule by default.",
    )


def _classify_schema_failure(
    *,
    expected_task_types: list[str],
    expected_missing_inputs: list[str],
    actual_missing_inputs: list[str],
) -> FailureClassification | None:
    if not expected_task_types:
        return None
    all_missing = [*expected_missing_inputs, *actual_missing_inputs]
    if any(value.startswith("conflict:") for value in all_missing):
        return None

    expected_set = set(expected_missing_inputs)
    actual_set = set(actual_missing_inputs)
    extra_actual = sorted(actual_set - expected_set)
    missing_expected = sorted(expected_set - actual_set)
    if not extra_actual and not missing_expected:
        return None

    catalog = TaskTypeSchemaCatalog()
    optional_inputs = {
        input_name
        for task_type in expected_task_types
        for input_name in catalog.optional_inputs_for(task_type)
    }

    optional_mismatch = sorted(
        {
            input_name
            for input_name in [*extra_actual, *missing_expected]
            if input_name in optional_inputs
        }
    )
    if optional_mismatch:
        return FailureClassification(
            error_type="WRONG_OPTIONAL_REQUIRED",
            confidence="high",
            reason=(
                "Optional task schema fields were treated as required: "
                + ", ".join(optional_mismatch)
                + "."
            ),
            suggested_action=(
                "Keep these fields optional and generate missing_inputs only from "
                "the task_type schema required_inputs list."
            ),
        )

    if extra_actual:
        return FailureClassification(
            error_type="UNNECESSARY_REQUIRED_INPUT",
            confidence="high",
            reason=(
                "Observed missing_inputs contains fields outside the expected task schema: "
                + ", ".join(extra_actual)
                + "."
            ),
            suggested_action=(
                "Narrow the task_type schema or validator; do not infer additional required "
                "fields from task descriptions."
            ),
        )

    return FailureClassification(
        error_type="MISSING_SCHEMA_FIELD",
        confidence="medium",
        reason=(
            "The benchmark expects required fields that were not produced by schema validation: "
            + ", ".join(missing_expected)
            + "."
        ),
        suggested_action=(
            "Review validation evidence and add the field to task_type schema only if it is "
            "truly required for this task type."
        ),
    )
