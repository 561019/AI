from evaluation.error_analysis.failure_classifier import classify_failure
from evaluation.error_analysis.context_recovery_analysis import (
    classify_context_recovery_failure,
    generate_context_recovery_reports,
)
from evaluation.error_analysis.blind_failure_abstraction import build_abstraction_report
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


def test_failure_classifier_marks_optional_field_as_wrong_required() -> None:
    case = {
        "intent_category": "clarification_evaluation",
        "expected_task_types": ["RULE_CALCULATION_COMMISSION"],
        "required_clarification": True,
        "missing_inputs": ["calculation_policy"],
    }
    failed = {
        "actual_task_types": ["RULE_CALCULATION_COMMISSION"],
        "task_type_exact": True,
        "expected_missing_inputs": ["calculation_policy"],
        "actual_missing_inputs": ["calculation_policy", "calculation_basis"],
    }

    classification = classify_failure(case, failed)

    assert classification.error_type == "WRONG_OPTIONAL_REQUIRED"


def test_failure_classifier_marks_missing_schema_field() -> None:
    case = {
        "intent_category": "clarification_evaluation",
        "expected_task_types": ["DOCUMENT_GENERATE"],
        "required_clarification": True,
        "missing_inputs": ["document_type"],
    }
    failed = {
        "actual_task_types": ["DOCUMENT_GENERATE"],
        "task_type_exact": True,
        "expected_missing_inputs": ["document_type"],
        "actual_missing_inputs": [],
    }

    classification = classify_failure(case, failed)

    assert classification.error_type == "MISSING_SCHEMA_FIELD"


def test_failure_classifier_marks_unnecessary_required_field() -> None:
    case = {
        "intent_category": "clarification_evaluation",
        "expected_task_types": ["DOCUMENT_GENERATE"],
        "required_clarification": True,
        "missing_inputs": [],
    }
    failed = {
        "actual_task_types": ["DOCUMENT_GENERATE"],
        "task_type_exact": True,
        "expected_missing_inputs": [],
        "actual_missing_inputs": ["project_name"],
    }

    classification = classify_failure(case, failed)

    assert classification.error_type == "UNNECESSARY_REQUIRED_INPUT"


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


def test_context_recovery_failure_classifier_prefers_context_match_error() -> None:
    case = {
        "id": "CTX-CASE-001",
        "text": "接着处理一下",
        "intent_category": "context_dependency",
        "expected_task_types": ["DOCUMENT_TABLE_PARSE"],
        "required_clarification": False,
        "missing_inputs": [],
        "context": {
            "conversation_context": [
                {
                    "task_type": "DOCUMENT_TABLE_PARSE",
                }
            ],
            "project_context": [],
            "user_project_context": [],
        },
    }
    failed = {
        "actual_task_types": ["FILE_STRUCTURE_EXTRACT"],
        "actual_missing_inputs": [],
        "actual_clarification": False,
    }

    classification = classify_context_recovery_failure(case, failed)

    assert classification["failure_type"] == "CONTEXT_MATCH_ERROR"


def test_context_recovery_report_redacts_blind_text(tmp_path) -> None:
    benchmark_report = {
        "total": 1,
        "passed": 0,
        "failed_cases": [
            {
                "id": "CTX-CASE-002",
                "text": "继续处理一下",
                "intent_category": "context_dependency",
                "expected_task_types": ["PROCESS_HANDLE"],
                "actual_task_types": ["DATA_QUERY_FETCH"],
                "expected_missing_inputs": [],
                "actual_missing_inputs": [],
                "required_clarification": False,
                "actual_clarification": False,
            }
        ],
    }
    dataset_dir = tmp_path / "datasets" / "blind_test"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    dataset_file = dataset_dir / "blind_test_v1.jsonl"
    dataset_file.write_text(
        __import__("json").dumps(
            {
                "id": "CTX-CASE-002",
                "text": "继续处理一下",
                "intent_category": "context_dependency",
                "expected_tasks": [{"task_type": "PROCESS_HANDLE"}],
                "expected_task_types": ["PROCESS_HANDLE"],
                "required_clarification": False,
                "missing_inputs": [],
                "forbidden_tasks": [],
                "context": {
                    "conversation_context": [
                        {
                            "task_type": "PROCESS_HANDLE",
                        }
                    ],
                    "project_context": [],
                    "user_project_context": [],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "blind_report.json"
    report_path.write_text(__import__("json").dumps(benchmark_report), encoding="utf-8")

    analysis, distribution = generate_context_recovery_reports(
        benchmark_report_path=report_path,
        dataset_root=tmp_path / "datasets",
        split="blind_test",
        allow_blind_test=True,
    )

    assert analysis["failure_cases"][0]["text_redacted"] is True
    assert "继续处理一下" not in __import__("json").dumps(analysis, ensure_ascii=False)
    assert distribution["failure_distribution"]["CONTEXT_MATCH_ERROR"] == 1


def test_blind_failure_abstraction_redacts_text_and_groups_capabilities(tmp_path) -> None:
    sealed_report = {
        "summary": {"total": 2, "passed": 0, "full_pass_rate": 0.0},
        "failures": [
            {
                "case_id": "BLIND-CTX",
                "input": "继续处理一下",
                "intent_category": "context_dependency",
                "failure_type": "CONTEXT_RECOVERY_ERROR",
                "failure_types": ["CONTEXT_RECOVERY_ERROR", "TASK_TYPE_ERROR"],
                "predicted_result": {"task_types": ["DATA_QUERY_FETCH"], "missing_inputs": []},
                "expected_result": {"task_types": ["PROCESS_HANDLE"], "missing_inputs": []},
            },
            {
                "case_id": "BLIND-CLARIFY",
                "input": "把这个弄一下",
                "intent_category": "insufficient_information",
                "failure_type": "CLARIFICATION_ERROR",
                "failure_types": ["CLARIFICATION_ERROR"],
                "predicted_result": {"task_types": ["DATA_ANALYSIS_PROBLEM"], "missing_inputs": ["analysis_object"], "clarification_required": True},
                "expected_result": {"task_types": [], "missing_inputs": [], "clarification_required": True},
            },
        ],
    }

    report = build_abstraction_report(sealed_report, sealed_report_path=tmp_path / "sealed.json")
    rendered = __import__("json").dumps(report, ensure_ascii=False)

    assert "继续处理一下" not in rendered
    assert "把这个弄一下" not in rendered
    assert report["failure_type_distribution"]["CONTEXT_RECOVERY_FAILURE"] == 1
    assert report["failure_type_distribution"]["CLARIFICATION_DECISION_FAILURE"] == 1
    assert report["failure_cases"][0]["text_redacted"] is True
