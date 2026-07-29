from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


ErrorType = Literal[
    "L1_RULE_MISS",
    "L2_SEMANTIC_MISS",
    "NEED_L3_OR_CLARIFICATION",
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
    task_type_exact = bool(failed_metric.get("task_type_exact"))

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
