import json

import pytest

from evaluation.benchmark.benchmark_runner import evaluate_case, load_cases, validation_report
from evaluation.benchmark.metrics import aggregate_case_metrics, evaluate_case_metrics
from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer


def test_benchmark_metrics_track_task_missing_and_forbidden_failures() -> None:
    metric = evaluate_case_metrics(
        case_id="case-001",
        text="后续可能考虑提醒，本次只分析销售异常。",
        split="validation",
        intent_category="future_scope",
        expected_task_types=["DATA_ANALYSIS_PROBLEM"],
        actual_task_types=["DATA_ANALYSIS_PROBLEM", "MONITORING_REMINDER"],
        expected_missing_inputs=[],
        actual_missing_inputs=["trigger_condition"],
        required_clarification=False,
        actual_clarification=True,
        forbidden_tasks=["MONITORING_REMINDER"],
        actual_task_descriptions=["分析销售异常", "创建监控提醒"],
        partial_coverage_rate=0.5,
        uncovered_segment_count=1,
        l3_compensation_attempted=True,
        l3_compensation_success=True,
    )

    report = aggregate_case_metrics([metric])

    assert metric.task_type_exact is False
    assert metric.missing_inputs_pass is False
    assert metric.forbidden_pass is False
    assert metric.full_pass is False
    assert report["forbidden_violation_count"] == 1
    assert report["future_scope_false_positive_rate"] == 1.0
    assert report["negation_false_positive_rate"] == 0.0
    assert report["by_intent_category"]["future_scope"]["forbidden_false_positive_rate"] == 1.0
    assert report["macro_f1"] < 1
    assert report["partial_coverage_rate"] == 0.5
    assert report["uncovered_segment_count"] == 1
    assert report["l3_compensation_success_rate"] == 1.0
    assert report["conflict_detection_accuracy"] == 1.0
    assert report["conflict_clarification_accuracy"] == 1.0
    assert report["false_resolution_rate"] == 0.0
    assert report["clarification_decision_accuracy"] == 0.0
    assert report["clarification_field_accuracy"] == 0.0
    assert report["clarification_question_accuracy"] == 0.0
    assert report["clarification_recovery_accuracy"] == 0.0
    assert report["missing_input_precision"] == 0.0
    assert report["missing_input_recall"] == 0.0
    assert report["over_clarification_rate"] == 1.0


def test_benchmark_metrics_track_conflict_failures() -> None:
    metric = evaluate_case_metrics(
        case_id="case-conflict-001",
        text="使用ERP生成销售报表",
        split="validation",
        intent_category="conflict_resolution",
        expected_task_types=["DOCUMENT_GENERATE"],
        actual_task_types=["DOCUMENT_GENERATE"],
        expected_missing_inputs=["conflict:DATA_SOURCE_CONFLICT"],
        actual_missing_inputs=[],
        required_clarification=True,
        actual_clarification=False,
        forbidden_tasks=[],
        expected_conflict_types=["DATA_SOURCE_CONFLICT"],
        actual_conflict_types=["DATA_SOURCE_CONFLICT"],
        actual_conflicts=[
            {
                "conflict_type": "DATA_SOURCE_CONFLICT",
                "resolution_status": "resolved",
            }
        ],
        expected_conflict_clarification=True,
    )

    report = aggregate_case_metrics([metric])

    assert metric.conflict_detection_pass is True
    assert metric.conflict_clarification_pass is False
    assert metric.false_resolution_pass is False
    assert metric.full_pass is False
    assert report["conflict_detection_accuracy"] == 1.0
    assert report["conflict_clarification_accuracy"] == 0.0
    assert report["false_resolution_rate"] == 1.0


def test_benchmark_metrics_track_clarification_question_quality() -> None:
    metric = evaluate_case_metrics(
        case_id="case-clarification-001",
        text="计算销售提成",
        split="validation",
        intent_category="clarification_evaluation",
        expected_task_types=["RULE_CALCULATION_COMMISSION"],
        actual_task_types=["RULE_CALCULATION_COMMISSION"],
        expected_missing_inputs=["calculation_policy", "sales_data_source"],
        actual_missing_inputs=["calculation_policy", "sales_data_source"],
        required_clarification=True,
        actual_clarification=True,
        expected_clarification_questions=[
            "请提供计算规则或适用政策。",
            "请提供销售数据来源（例如数据库、文件或业务系统）。",
        ],
        actual_clarification_questions=[
            "请提供计算规则或适用政策。",
            "请提供销售数据来源（例如数据库、文件或业务系统）。",
            "请确认统计范围（例如时间范围、组织范围）。",
        ],
        max_extra_clarification_questions=0,
        forbidden_tasks=[],
    )

    report = aggregate_case_metrics([metric])

    assert metric.clarification_decision_pass is True
    assert metric.clarification_field_pass is True
    assert metric.clarification_question_pass is True
    assert metric.unnecessary_clarification_question_pass is False
    assert metric.extra_clarification_questions == ["请确认统计范围（例如时间范围、组织范围）。"]
    assert metric.full_pass is False
    assert report["clarification_question_accuracy"] == 1.0
    assert report["no_unnecessary_clarification_question_accuracy"] == 0.0
    assert report["unnecessary_clarification_question_rate"] == 1.0


def test_benchmark_metrics_track_clarification_recovery() -> None:
    metric = evaluate_case_metrics(
        case_id="case-clarification-002",
        text="计算销售提成",
        split="validation",
        intent_category="clarification_evaluation",
        expected_task_types=["RULE_CALCULATION_COMMISSION"],
        actual_task_types=["RULE_CALCULATION_COMMISSION"],
        expected_missing_inputs=["calculation_policy"],
        actual_missing_inputs=["calculation_policy"],
        required_clarification=True,
        actual_clarification=True,
        forbidden_tasks=[],
        clarification_recovery={
            "attempted": True,
            "passed": True,
            "task_id_preserved": True,
            "actual_status": "ready",
            "actual_final_inputs": {"calculation_policy": "2026规则"},
        },
    )

    report = aggregate_case_metrics([metric])

    assert metric.clarification_recovery_attempted is True
    assert metric.clarification_recovery_pass is True
    assert metric.full_pass is True
    assert report["clarification_recovery_accuracy"] == 1.0


def test_benchmark_runner_evaluates_clarification_recovery() -> None:
    analyzer = StandardIntentAnalyzer(
        registry=FunctionRegistryCatalog(),
        semantic_matcher=None,
        llm_analyzer=None,
        intent_record_service=None,
    )
    metric = evaluate_case(
        analyzer=analyzer,
        case={
            "id": "BENCH-VALIDATION-CLARIFICATION-UNIT",
            "_split": "validation",
            "text": "\u8ba1\u7b97\u9500\u552e\u63d0\u6210",
            "intent_category": "clarification_evaluation",
            "expected_tasks": [{"task_type": "RULE_CALCULATION_COMMISSION"}],
            "expected_task_types": ["RULE_CALCULATION_COMMISSION"],
            "required_clarification": True,
            "missing_inputs": ["calculation_policy"],
            "expected_clarification_questions": [
                "\u8bf7\u63d0\u4f9b\u8ba1\u7b97\u89c4\u5219\u6216\u9002\u7528\u653f\u7b56\u3002",
            ],
            "max_extra_clarification_questions": 0,
            "forbidden_tasks": [],
            "clarification_answer": "\u4f7f\u75282026\u89c4\u5219\uff0c\u534e\u4e1c\u533a\u57df\uff0cERP\u6570\u636e",
            "expected_recovery_status": "ready",
            "expected_recovery_missing_inputs": [],
            "expected_recovery_final_inputs": {
                "calculation_policy": "2026\u89c4\u5219",
            },
        },
    )

    assert metric.clarification_decision_pass is True
    assert metric.clarification_field_pass is True
    assert metric.clarification_question_pass is True
    assert metric.unnecessary_clarification_question_pass is True
    assert metric.clarification_recovery_pass is True
    assert metric.clarification_recovery["task_id_preserved"] is True


def test_benchmark_loader_protects_blind_test_split(tmp_path) -> None:
    blind_dir = tmp_path / "blind_test"
    blind_dir.mkdir(parents=True)
    (blind_dir / "blind_test_v1.jsonl").write_text(
        json.dumps(
            {
                "id": "BENCH-BLIND_TEST-001",
                "text": "计算销售提成",
                "intent_category": "short_instruction",
                "expected_tasks": [{"task_type": "RULE_CALCULATION_COMMISSION"}],
                "expected_task_types": ["RULE_CALCULATION_COMMISSION"],
                "required_clarification": True,
                "missing_inputs": ["calculation_policy", "sales_data_source"],
                "forbidden_tasks": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="blind_test is protected"):
        load_cases(
            dataset_root=tmp_path,
            dataset=None,
            split="blind_test",
            allow_blind_test=False,
        )

    cases = load_cases(
        dataset_root=tmp_path,
        dataset=None,
        split="blind_test",
        allow_blind_test=True,
    )

    assert validation_report(cases) == {
        "total": 1,
        "by_split": {"blind_test": 1},
        "by_intent_category": {"short_instruction": 1},
        "ids_are_unique": True,
    }
