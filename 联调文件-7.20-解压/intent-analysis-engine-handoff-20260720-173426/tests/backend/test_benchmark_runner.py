import json

import pytest

from evaluation.benchmark.benchmark_runner import load_cases, validation_report
from evaluation.benchmark.metrics import aggregate_case_metrics, evaluate_case_metrics


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
    assert report["macro_f1"] < 1
    assert report["partial_coverage_rate"] == 0.5
    assert report["uncovered_segment_count"] == 1
    assert report["l3_compensation_success_rate"] == 1.0


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
