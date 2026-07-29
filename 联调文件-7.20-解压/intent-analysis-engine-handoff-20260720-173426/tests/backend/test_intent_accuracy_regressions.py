import json
from pathlib import Path

from evaluation_runner import build_analyzer


REGRESSION_CASES_PATH = Path(__file__).resolve().parents[2] / "evaluation" / "regression_cases.json"


def test_rule_priority_and_semantic_regression_cases() -> None:
    analyzer = build_analyzer(semantic_mode="local", llm_mode="off", semantic_threshold=0.50)
    regression_cases = json.loads(REGRESSION_CASES_PATH.read_text(encoding="utf-8"))

    for case in regression_cases:
        analysis = analyzer.analyze_with_debug(
            text=case["text"],
            user_id="regression-test",
            conversation_id="regression-test",
        )

        expected_tasks = _parse_expected_result(case["expected_result"])
        actual_tasks = [task.task_type for task in analysis.result.tasks]

        assert actual_tasks == expected_tasks, case["text"]


def test_decomposes_sales_data_commission_and_voucher_request() -> None:
    analyzer = build_analyzer(semantic_mode="local", llm_mode="off", semantic_threshold=0.50)

    analysis = analyzer.analyze_with_debug(
        text="把上个月各区域销售数据整理出来，算提成，再生成凭证",
        user_id="regression-test",
        conversation_id="regression-test",
    )

    result = analysis.result
    assert analysis.debug["level1_rule_result"]["rule"] == "task_decomposer"
    assert result.clarification_required is False
    assert [task.task_name for task in result.tasks] == [
        "获取销售明细",
        "根据政策计算销售提成",
        "生成计提凭证",
    ]
    assert [task.task_type for task in result.tasks] == [
        "DATA_QUERY_FETCH",
        "RULE_CALCULATION_COMMISSION",
        "DIGITAL_ASSET_ACCRUAL_VOUCHER",
    ]
    assert "period:上个月" in result.tasks[0].required_inputs
    assert "classification_field:区域" in result.tasks[0].required_inputs
    assert "statistical_range:上个月" in result.tasks[1].required_inputs
    assert "asset_type:计提凭证" in result.tasks[2].required_inputs
    assert result.tasks[1].dependencies == [result.tasks[0].task_id]
    assert result.tasks[2].dependencies == [result.tasks[1].task_id]


def _parse_expected_result(expected_result: str) -> list[str]:
    tasks = []
    for part in expected_result.split("->"):
        _, task_type = [value.strip() for value in part.split("/", maxsplit=1)]
        tasks.append(task_type)
    return tasks
