from evaluation.error_analysis.failure_classifier import classify_failure
from evaluation.error_analysis.report_generator import generate_optimization_report


def test_failure_classifier_keeps_protected_false_positive_out_of_l1_l2() -> None:
    case = {
        "intent_category": "future_scope",
        "expected_task_types": ["DATA_FILTER"],
        "required_clarification": False,
    }
    failed = {
        "actual_task_types": ["MONITORING_REMINDER", "DATA_FILTER"],
        "forbidden_violations": ["MONITORING_REMINDER"],
        "task_type_exact": False,
    }

    classification = classify_failure(case, failed)

    assert classification.error_type == "NEED_L3_OR_CLARIFICATION"
    assert "Do not expand L1/L2" in classification.reason


def test_failure_classifier_allows_only_safe_colloquial_semantic_miss() -> None:
    case = {
        "intent_category": "colloquial_expression",
        "expected_task_types": ["DATA_SORT"],
        "required_clarification": False,
    }
    failed = {
        "actual_task_types": ["DATA_ANALYSIS_YOY"],
        "forbidden_violations": [],
        "task_type_exact": False,
    }

    classification = classify_failure(case, failed)

    assert classification.error_type == "L2_SEMANTIC_MISS"
    assert classification.confidence == "high"


def test_optimization_report_marks_rollback_when_forbidden_rate_regresses(tmp_path) -> None:
    before = {
        "task_type_exact_accuracy": 0.5,
        "macro_recall": 0.5,
        "forbidden_pass_rate": 1.0,
        "clarification_accuracy": 0.7,
        "by_intent_category": {
            "future_scope": {"forbidden_pass_rate": 1.0},
            "negation_expression": {"forbidden_pass_rate": 1.0},
        },
        "failed_cases": [
            {"id": "case-001", "f1": 0.0},
        ],
    }
    after = {
        "task_type_exact_accuracy": 0.6,
        "macro_recall": 0.6,
        "forbidden_pass_rate": 0.9,
        "clarification_accuracy": 0.7,
        "by_intent_category": {
            "future_scope": {"forbidden_pass_rate": 1.0},
            "negation_expression": {"forbidden_pass_rate": 1.0},
        },
        "failed_cases": [],
    }
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(__import__("json").dumps(before), encoding="utf-8")
    after_path.write_text(__import__("json").dumps(after), encoding="utf-8")

    report = generate_optimization_report(
        before_report_path=before_path,
        after_report_path=after_path,
        failure_report={"by_error_type": {}},
        added_rule_count=1,
        added_semantic_example_count=0,
    )

    assert report["rollback_required"] is True
    assert report["improved_cases"] == ["case-001"]

