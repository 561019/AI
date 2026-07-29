from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "evaluation" / "benchmark" / "ad_hoc_unseen_report_20260727.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation_runner import build_analyzer  # noqa: E402
from app.services.conversation_understanding import ConversationUnderstandingLayer  # noqa: E402


SINGLE_CASES: list[dict[str, Any]] = [
    {
        "id": "UNSEEN-S-001",
        "category": "single_business",
        "text": "麻烦把一季度华南各门店回款金额拉出来。",
        "expected_tasks": ["DATA_QUERY_FETCH"],
        "should_clarify": True,
    },
    {
        "id": "UNSEEN-S-002",
        "category": "single_business",
        "text": "把三月份逾期超过45天的客户挑出来。",
        "expected_tasks": ["DATA_FILTER"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-003",
        "category": "single_business",
        "text": "按客户等级汇总本周新增线索数量。",
        "expected_tasks": ["DATA_AGGREGATION_SUMMARY"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-004",
        "category": "single_business",
        "text": "帮我做一下本月费用环比。",
        "expected_tasks": ["DATA_ANALYSIS_MOM"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-005",
        "category": "single_business",
        "text": "照新版绩效规则算一下客服奖金。",
        "expected_tasks": ["RULE_CALCULATION_GENERAL"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-006",
        "category": "single_business",
        "text": "用最新提成规则重新核一下上季度销售提成。",
        "expected_tasks": ["RULE_CALCULATION_COMMISSION"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-007",
        "category": "single_multitask",
        "text": "把上周客服投诉整理成问题清单，再给出整改建议。",
        "expected_tasks": ["COMPLAINT_INFORMATION_ORGANIZE", "DATA_ANALYSIS_PROBLEM", "IMPROVEMENT_PLAN_GENERATE"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-008",
        "category": "single_business",
        "text": "查一下公司加班餐补标准。",
        "expected_tasks": ["QUESTION_ANSWER"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-009",
        "category": "single_business",
        "text": "写一封通知，让各部门周五前提交预算说明。",
        "expected_tasks": ["CONTENT_GENERATE"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-010",
        "category": "single_business",
        "text": "生成门店开业宣传海报。",
        "expected_tasks": ["MULTIMEDIA_GENERATE"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-011",
        "category": "single_business",
        "text": "启动供应商准入审批。",
        "expected_tasks": ["WORKFLOW_START"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-012",
        "category": "single_business",
        "text": "合同还有15天到期时提醒法务。",
        "expected_tasks": ["MONITORING_REMINDER"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-013",
        "category": "scope_filter",
        "text": "不要现在分析销售数据，下周再说。",
        "expected_tasks": [],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-014",
        "category": "scope_filter",
        "text": "先不用生成报告，也不要查数据。",
        "expected_tasks": [],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-015",
        "category": "low_information",
        "text": "这个处理一下。",
        "expected_tasks": [],
        "should_clarify": True,
    },
    {
        "id": "UNSEEN-S-016",
        "category": "single_multitask",
        "text": "把ERP里的采购入库记录取出来，筛出未匹配发票的，再提交到OA。",
        "expected_tasks": ["EXTERNAL_DATA_FETCH", "DATA_FILTER", "EXTERNAL_SYSTEM_SUBMIT"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-017",
        "category": "single_multitask",
        "text": "统计一下各区域销售额并按金额倒序排列。",
        "expected_tasks": ["DATA_AGGREGATION_SUMMARY", "DATA_SORT"],
        "should_clarify": True,
    },
    {
        "id": "UNSEEN-S-018",
        "category": "single_multitask",
        "text": "分析客户流失原因并预测下季度流失风险。",
        "expected_tasks": ["DATA_ANALYSIS_PROBLEM", "DATA_ANALYSIS_FORECAST"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-019",
        "category": "single_multitask",
        "text": "解析发票附件并提取金额、税号字段。",
        "expected_tasks": ["DOCUMENT_TABLE_PARSE", "FILE_STRUCTURE_EXTRACT"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-S-020",
        "category": "single_business",
        "text": "根据本月提成计算结果生成计提凭证。",
        "expected_tasks": ["DIGITAL_ASSET_ACCRUAL_VOUCHER"],
        "should_clarify": False,
    },
]


LONG_DIALOGUE_CASES: list[dict[str, Any]] = [
    {
        "id": "UNSEEN-D-001",
        "category": "context_ellipsis",
        "conversation": [
            {"role": "user", "text": "请先核算华东上月销售提成。"},
            {"role": "assistant", "text": "已识别销售提成计算任务。"},
            {"role": "user", "text": "再算一遍。"},
        ],
        "expected_tasks": ["RULE_CALCULATION_COMMISSION"],
        "should_clarify": True,
    },
    {
        "id": "UNSEEN-D-002",
        "category": "context_ellipsis",
        "conversation": [
            {"role": "user", "text": "帮我生成一份销售经营周报。"},
            {"role": "assistant", "text": "已识别文档生成任务。"},
            {"role": "user", "text": "继续修改。"},
        ],
        "expected_tasks": ["DOCUMENT_GENERATE"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-D-003",
        "category": "context_ambiguous",
        "conversation": [
            {"role": "user", "text": "查询库存数据。"},
            {"role": "assistant", "text": "已识别查询任务。"},
            {"role": "user", "text": "分析销售下降原因。"},
            {"role": "assistant", "text": "已识别分析任务。"},
            {"role": "user", "text": "继续处理。"},
        ],
        "expected_tasks": [],
        "should_clarify": True,
    },
    {
        "id": "UNSEEN-D-004",
        "category": "context_missing",
        "conversation": [{"role": "user", "text": "重新看看。"}],
        "expected_tasks": [],
        "should_clarify": True,
    },
    {
        "id": "UNSEEN-D-005",
        "category": "context_reference",
        "conversation": [
            {"role": "user", "text": "我们这周要准备客户经营复盘，前面说的组织安排不用管。"},
            {"role": "assistant", "text": "请继续说明需要识别的任务。"},
            {"role": "user", "text": "从CRM拉本季度重点客户名单。"},
            {"role": "assistant", "text": "已识别客户资料获取任务。"},
            {"role": "user", "text": "再筛一版高价值的。"},
        ],
        "expected_tasks": ["DATA_FILTER"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-D-006",
        "category": "context_reference",
        "conversation": [
            {"role": "user", "text": "读取这份合同PDF。"},
            {"role": "assistant", "text": "已识别文件解析任务。"},
            {"role": "user", "text": "这个字段结构也提一下。"},
        ],
        "expected_tasks": ["FILE_STRUCTURE_EXTRACT"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-D-007",
        "category": "context_reference",
        "conversation": [
            {"role": "user", "text": "统计各区域订单数量。"},
            {"role": "assistant", "text": "已识别汇总任务。"},
            {"role": "user", "text": "和去年同期比一下。"},
        ],
        "expected_tasks": ["DATA_ANALYSIS_YOY"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-D-008",
        "category": "context_reference",
        "conversation": [
            {"role": "user", "text": "分析客户投诉增长原因。"},
            {"role": "assistant", "text": "已识别问题分析任务。"},
            {"role": "user", "text": "按这个生成整改方案。"},
        ],
        "expected_tasks": ["IMPROVEMENT_PLAN_GENERATE"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-D-009",
        "category": "context_reference",
        "conversation": [
            {"role": "user", "text": "分析库存缺货风险。"},
            {"role": "assistant", "text": "已识别库存风险分析。"},
            {"role": "user", "text": "上面那个结果每天提醒我。"},
        ],
        "expected_tasks": ["MONITORING_REMINDER"],
        "should_clarify": False,
    },
    {
        "id": "UNSEEN-D-010",
        "category": "context_override",
        "conversation": [
            {"role": "user", "text": "先核算销售提成。"},
            {"role": "assistant", "text": "已识别提成核算。"},
            {"role": "user", "text": "不用了，改成生成销售日报。"},
        ],
        "expected_tasks": ["DOCUMENT_GENERATE"],
        "should_clarify": False,
    },
]


def main() -> int:
    _configure_stdout()
    analyzer = build_analyzer(semantic_mode="local", llm_mode="off", semantic_threshold=0.50)
    layer = ConversationUnderstandingLayer(analyzer)

    rows = [run_single(layer, case) for case in SINGLE_CASES]
    rows.extend(run_dialogue(layer, case) for case in LONG_DIALOGUE_CASES)
    summary = summarize(rows)
    summary["run_mode"] = {
        "semantic_mode": "local",
        "llm_mode": "off",
        "semantic_threshold": 0.50,
    }
    summary["sample_duplicate_check"] = duplicate_check()

    REPORT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print_report(summary)
    return 0


def run_single(layer: ConversationUnderstandingLayer, case: dict[str, Any]) -> dict[str, Any]:
    analysis = layer.analyze_with_debug(
        text=case["text"],
        user_id="ad-hoc-unseen",
        conversation_id=case["id"],
        history=[],
    )
    return make_row(
        case,
        analysis.result,
        analysis.debug,
        input_text=case["text"],
        kind="single",
    )


def run_dialogue(layer: ConversationUnderstandingLayer, case: dict[str, Any]) -> dict[str, Any]:
    messages = case["conversation"]
    current_index = max(index for index, message in enumerate(messages) if message["role"] == "user")
    current = messages[current_index]
    history = messages[:current_index]
    analysis = layer.analyze_with_debug(
        text=current["text"],
        user_id="ad-hoc-unseen",
        conversation_id=case["id"],
        history=history,
    )
    return make_row(
        case,
        analysis.result,
        analysis.debug,
        input_text=current["text"],
        kind="dialogue",
    )


def make_row(
    case: dict[str, Any],
    result: Any,
    debug: dict[str, Any],
    *,
    input_text: str,
    kind: str,
) -> dict[str, Any]:
    actual_tasks = [task.task_type for task in result.tasks]
    expected_tasks = case["expected_tasks"]
    task_type_pass = actual_tasks == expected_tasks
    clarification_pass = bool(result.clarification_required) == bool(case["should_clarify"])
    decomposition_pass = len(actual_tasks) == len(expected_tasks)
    return {
        "id": case["id"],
        "kind": kind,
        "category": case["category"],
        "text": input_text,
        "expected_tasks": expected_tasks,
        "actual_tasks": actual_tasks,
        "expected_clarification": bool(case["should_clarify"]),
        "actual_clarification": bool(result.clarification_required),
        "missing_inputs": [task.missing_inputs for task in result.tasks],
        "clarification_questions": result.clarification_questions,
        "analysis_level": result.analysis_level,
        "selected_by": selected_by(debug),
        "task_type_pass": task_type_pass,
        "clarification_pass": clarification_pass,
        "decomposition_pass": decomposition_pass,
        "passed": task_type_pass and clarification_pass and decomposition_pass,
    }


def selected_by(debug: dict[str, Any]) -> str | None:
    decision = debug.get("final_decision")
    if isinstance(decision, dict):
        value = decision.get("selected_by")
        return str(value) if value is not None else None
    return None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    single_rows = [row for row in rows if row["kind"] == "single"]
    dialogue_rows = [row for row in rows if row["kind"] == "dialogue"]
    expected_empty = [row for row in rows if not row["expected_tasks"]]
    false_positive_count = sum(1 for row in expected_empty if row["actual_tasks"])
    context_rows = [
        row
        for row in dialogue_rows
        if row["category"] in {"context_ellipsis", "context_reference", "context_override"}
    ]
    return {
        "total": len(rows),
        "full_pass_rate": ratio(rows, "passed"),
        "task_type_accuracy": ratio(rows, "task_type_pass"),
        "clarification_accuracy": ratio(rows, "clarification_pass"),
        "decomposition_accuracy": ratio(rows, "decomposition_pass"),
        "false_positive_rate_on_no_task_cases": (
            false_positive_count / len(expected_empty) if expected_empty else 0.0
        ),
        "false_positive_count_on_no_task_cases": false_positive_count,
        "no_task_case_count": len(expected_empty),
        "context_recovery_accuracy": ratio(context_rows, "task_type_pass"),
        "context_case_count": len(context_rows),
        "single": summarize_subset(single_rows),
        "long_dialogue": summarize_subset(dialogue_rows),
        "by_category": {
            category: summarize_subset(items)
            for category, items in sorted(group_by(rows, "category").items())
        },
        "failed_cases": [row for row in rows if not row["passed"]],
        "rows": rows,
    }


def summarize_subset(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(rows),
        "full_pass_rate": ratio(rows, "passed"),
        "task_type_accuracy": ratio(rows, "task_type_pass"),
        "clarification_accuracy": ratio(rows, "clarification_pass"),
        "decomposition_accuracy": ratio(rows, "decomposition_pass"),
        "passed_cases": sum(1 for row in rows if row["passed"]),
    }


def ratio(rows: list[dict[str, Any]], field: str) -> float:
    return sum(1 for row in rows if row[field]) / len(rows) if rows else 0.0


def group_by(rows: list[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row[field], []).append(row)
    return grouped


def duplicate_check() -> dict[str, Any]:
    known_texts = load_non_blind_known_texts()
    sample_texts = [case["text"] for case in SINGLE_CASES]
    for case in LONG_DIALOGUE_CASES:
        sample_texts.extend(message["text"] for message in case["conversation"] if message["role"] == "user")
    duplicates = sorted(text for text in sample_texts if text in known_texts)
    return {
        "checked_against": [
            "evaluation/dataset/intent_test_dataset.json",
            "evaluation/conversation_dataset.json",
            "evaluation/long_text_dataset.json",
            "evaluation/benchmark/datasets/train/*.jsonl",
            "evaluation/benchmark/datasets/validation/*.jsonl",
        ],
        "blind_test_used": False,
        "exact_duplicate_count": len(duplicates),
        "exact_duplicates": duplicates,
    }


def load_non_blind_known_texts() -> set[str]:
    paths = [
        PROJECT_ROOT / "evaluation" / "dataset" / "intent_test_dataset.json",
        PROJECT_ROOT / "evaluation" / "conversation_dataset.json",
        PROJECT_ROOT / "evaluation" / "long_text_dataset.json",
    ]
    paths.extend((PROJECT_ROOT / "evaluation" / "benchmark" / "datasets" / "train").glob("*.jsonl"))
    paths.extend((PROJECT_ROOT / "evaluation" / "benchmark" / "datasets" / "validation").glob("*.jsonl"))

    texts: set[str] = set()
    for path in paths:
        if not path.exists() or "blind_test" in path.as_posix():
            continue
        if path.suffix == ".jsonl":
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    collect_texts(json.loads(line), texts)
        else:
            collect_texts(json.loads(path.read_text(encoding="utf-8")), texts)
    return texts


def collect_texts(value: Any, texts: set[str]) -> None:
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            texts.add(text)
        conversation = value.get("conversation")
        if isinstance(conversation, list):
            for message in conversation:
                collect_texts(message, texts)
        for key in ("history", "messages"):
            nested = value.get(key)
            if isinstance(nested, list):
                for item in nested:
                    collect_texts(item, texts)
    elif isinstance(value, list):
        for item in value:
            collect_texts(item, texts)


def print_report(summary: dict[str, Any]) -> None:
    print(f"Report saved: {REPORT_PATH.relative_to(PROJECT_ROOT)}")
    print(f"Total: {summary['total']}")
    print(f"Full pass: {summary['single']['passed_cases'] + summary['long_dialogue']['passed_cases']}/{summary['total']} = {summary['full_pass_rate']:.2%}")
    print(f"Task type accuracy: {summary['task_type_accuracy']:.2%}")
    print(f"Clarification accuracy: {summary['clarification_accuracy']:.2%}")
    print(f"Decomposition accuracy: {summary['decomposition_accuracy']:.2%}")
    print(
        "False positive rate on no-task cases: "
        f"{summary['false_positive_rate_on_no_task_cases']:.2%} "
        f"({summary['false_positive_count_on_no_task_cases']}/{summary['no_task_case_count']})"
    )
    print(
        "Context recovery accuracy: "
        f"{summary['context_recovery_accuracy']:.2%} "
        f"({round(summary['context_recovery_accuracy'] * summary['context_case_count'])}/{summary['context_case_count']})"
    )
    print(
        "Exact duplicate count against non-blind datasets: "
        f"{summary['sample_duplicate_check']['exact_duplicate_count']}"
    )
    print("By category:")
    for category, item in summary["by_category"].items():
        print(
            f"- {category}: full={item['full_pass_rate']:.2%}, "
            f"task={item['task_type_accuracy']:.2%}, "
            f"clarify={item['clarification_accuracy']:.2%}, n={item['total']}"
        )
    print("Failures:")
    for row in summary["failed_cases"]:
        print(f"- {row['id']} [{row['category']}] {row['text']}")
        print(f"  expected={row['expected_tasks']} clarify={row['expected_clarification']}")
        print(
            f"  actual  ={row['actual_tasks']} clarify={row['actual_clarification']} "
            f"selected_by={row['selected_by']} missing={row['missing_inputs']}"
        )


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
