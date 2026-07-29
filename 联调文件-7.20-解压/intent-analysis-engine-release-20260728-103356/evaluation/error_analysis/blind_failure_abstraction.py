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
DEFAULT_SEALED_REPORT = PROJECT_ROOT / "evaluation" / "benchmark" / "blind_test_report.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "evaluation" / "error_analysis" / "blind_failure_abstraction_report.json"

for path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


ABSTRACT_FAILURE_TYPES = (
    "CONTEXT_RECOVERY_FAILURE",
    "TASK_GENERALIZATION_FAILURE",
    "CLARIFICATION_DECISION_FAILURE",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize sealed blind-test failures into abstract capability buckets. "
            "The report redacts blind text and is only for validation-planning."
        )
    )
    parser.add_argument("--sealed-report", type=Path, default=DEFAULT_SEALED_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_abstraction_report(read_json(args.sealed_report), sealed_report_path=args.sealed_report)
    write_json(args.output, report)
    print(f"Blind failure abstraction report written: {args.output}")
    print(f"Blind text policy: {report['blind_text_policy']}")
    print("Abstract failure distribution:")
    for failure_type, count in report["failure_type_distribution"].items():
        print(f"- {failure_type}: {count}")
    return 0


def build_abstraction_report(sealed_report: dict[str, Any], *, sealed_report_path: Path) -> dict[str, Any]:
    failures = [
        abstract_failure(row)
        for row in sealed_report.get("failures", [])
        if isinstance(row, dict)
    ]
    distribution = Counter(row["abstract_failure_type"] for row in failures)
    by_category: dict[str, Counter[str]] = {}
    for row in failures:
        category = row["intent_category"] or "unknown"
        by_category.setdefault(category, Counter())
        by_category[category][row["abstract_failure_type"]] += 1

    return {
        "report_type": "blind_failure_abstraction",
        "source_report": str(sealed_report_path),
        "split": "blind_test",
        "sealed": True,
        "development_use": "aggregate_and_abstract_only",
        "blind_text_policy": (
            "Raw blind_test text is intentionally omitted. Use only aggregate categories, "
            "task labels, and abstract validation plans."
        ),
        "guardrails": {
            "do_not_add_blind_case_to_validation": True,
            "do_not_add_blind_text_keyword_rules": True,
            "do_not_change_prompt_for_blind": True,
            "allowed_use": "identify common capability gaps and design independent validation samples",
        },
        "full_pass": sealed_report.get("summary", {}),
        "failure_type_distribution": {
            failure_type: distribution.get(failure_type, 0)
            for failure_type in ABSTRACT_FAILURE_TYPES
        },
        "by_intent_category": {
            category: dict(counter)
            for category, counter in sorted(by_category.items())
        },
        "common_problem_summary": common_problem_summary(distribution),
        "validation_planning": validation_planning(distribution),
        "failure_cases": failures,
    }


def abstract_failure(row: dict[str, Any]) -> dict[str, Any]:
    predicted = row.get("predicted_result") if isinstance(row.get("predicted_result"), dict) else {}
    expected = row.get("expected_result") if isinstance(row.get("expected_result"), dict) else {}
    raw_failure_types = [str(value) for value in row.get("failure_types", [])]
    intent_category = str(row.get("intent_category") or "")
    abstract_type = classify_abstract_failure(
        intent_category=intent_category,
        failure_type=str(row.get("failure_type") or ""),
        failure_types=raw_failure_types,
        expected=expected,
        predicted=predicted,
    )
    return {
        "case_id": row.get("case_id"),
        "text_sha256_12": short_hash(row.get("input", "")),
        "text_redacted": True,
        "intent_category": intent_category,
        "expected_task_types": list(expected.get("task_types") or []),
        "actual_task_types": list(predicted.get("task_types") or []),
        "expected_clarification": bool(expected.get("clarification_required", False)),
        "actual_clarification": bool(predicted.get("clarification_required", False)),
        "expected_missing_inputs": list(expected.get("missing_inputs") or []),
        "actual_missing_inputs": list(predicted.get("missing_inputs") or []),
        "sealed_primary_failure_type": row.get("failure_type"),
        "sealed_failure_types": raw_failure_types,
        "abstract_failure_type": abstract_type,
        "abstract_issue_pattern": issue_pattern(abstract_type, intent_category, raw_failure_types),
        "optimization_direction": optimization_direction(abstract_type),
    }


def classify_abstract_failure(
    *,
    intent_category: str,
    failure_type: str,
    failure_types: list[str],
    expected: dict[str, Any],
    predicted: dict[str, Any],
) -> str:
    if intent_category in {"context_dependency", "omitted_expression"} or failure_type == "CONTEXT_RECOVERY_ERROR":
        return "CONTEXT_RECOVERY_FAILURE"

    expected_clarification = bool(expected.get("clarification_required", False))
    actual_clarification = bool(predicted.get("clarification_required", False))
    expected_missing = set(expected.get("missing_inputs") or [])
    actual_missing = set(predicted.get("missing_inputs") or [])
    task_types_match = list(expected.get("task_types") or []) == list(predicted.get("task_types") or [])

    if (
        intent_category in {"ambiguous_request", "insufficient_information", "clarification_evaluation"}
        or "MISSING_INPUT_ERROR" in failure_types
        or "CLARIFICATION_ERROR" in failure_types
    ) and (
        task_types_match
        or expected_clarification != actual_clarification
        or expected_missing != actual_missing
    ):
        return "CLARIFICATION_DECISION_FAILURE"

    return "TASK_GENERALIZATION_FAILURE"


def issue_pattern(abstract_type: str, intent_category: str, failure_types: list[str]) -> str:
    if abstract_type == "CONTEXT_RECOVERY_FAILURE":
        if "TASK_TYPE_ERROR" in failure_types:
            return "short follow-up accepted a standalone task interpretation instead of recent context"
        return "short follow-up failed to bind to usable recent context"
    if abstract_type == "CLARIFICATION_DECISION_FAILURE":
        if "MISSING_INPUT_ERROR" in failure_types:
            return "schema-required input presence was over- or under-estimated"
        return "insufficient or ambiguous request produced the wrong clarification decision"
    if intent_category in {"negation_expression", "future_scope"}:
        return "protected-scope filtering preserved false-positive safety but lost the current actionable task"
    return "business wording did not generalize to the intended task type"


def optimization_direction(abstract_type: str) -> str:
    if abstract_type == "CONTEXT_RECOVERY_FAILURE":
        return "Add independent validation cases for ellipsis families and context-first recovery; tune resolver priority."
    if abstract_type == "CLARIFICATION_DECISION_FAILURE":
        return "Add independent validation cases for low-information requests and schema-required input source checks."
    return "Add semantic examples and generic matcher coverage for business wording families, without blind text keywords."


def common_problem_summary(distribution: Counter[str]) -> list[str]:
    summary = []
    if distribution["CONTEXT_RECOVERY_FAILURE"]:
        summary.append(
            "Context recovery is the largest generic gap: omitted follow-ups either do not parse or lose to weak standalone matching."
        )
    if distribution["TASK_GENERALIZATION_FAILURE"]:
        summary.append(
            "Task generalization needs broader business-language coverage for filtering, file-structure, external submit, multimedia, and protected-scope current tasks."
        )
    if distribution["CLARIFICATION_DECISION_FAILURE"]:
        summary.append(
            "Clarification decisions need stricter separation between business object and true schema-required input source."
        )
    return summary


def validation_planning(distribution: Counter[str]) -> list[dict[str, str]]:
    plans = []
    if distribution["CONTEXT_RECOVERY_FAILURE"]:
        plans.append(
            {
                "abstract_capability": "ellipsis + single recent context",
                "validation_case_family": "repeat/continue/status/field follow-ups across filter, document, and workflow tasks",
                "expected_behavior": "recover conversation context before L1/L2 semantic matching; clarify on no or ambiguous context",
            }
        )
    if distribution["TASK_GENERALIZATION_FAILURE"]:
        plans.append(
            {
                "abstract_capability": "business wording generalization",
                "validation_case_family": "colloquial filter, file structure, external submit, and multimedia current-task expressions",
                "expected_behavior": "identify the intended task type without adding blind-specific keywords",
            }
        )
    if distribution["CLARIFICATION_DECISION_FAILURE"]:
        plans.append(
            {
                "abstract_capability": "schema-driven clarification",
                "validation_case_family": "clear action/object but missing source, and low-information pronoun requests",
                "expected_behavior": "ask only for schema-required fields and avoid task guesses when object/action is absent",
            }
        )
    return plans


def short_hash(text: Any) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
