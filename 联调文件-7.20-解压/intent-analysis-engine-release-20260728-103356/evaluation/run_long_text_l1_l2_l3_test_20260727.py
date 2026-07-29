from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
REPORT_PATH = PROJECT_ROOT / "evaluation" / "benchmark" / "long_text_l1_l2_l3_report_20260727.json"

for path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evaluation_runner import build_analyzer  # noqa: E402
from app.services.conversation_understanding import ConversationUnderstandingLayer  # noqa: E402


BACKGROUND = (
    "本次分析需要统一业务口径，并保留原始数据，不改变原始字段名称。"
    "所有时间范围均以系统入账时间为准，区域字段使用客户所属区域，客户等级使用主数据中的当前等级。"
    "如果同一客户存在多条记录，需要保留明细并在汇总时说明去重方式。"
    "对于缺失值、重复值、异常值和跨季度数据，需要标记处理状态，不能因为缺少信息而擅自补全。"
    "最终输出只需要任务清单，不执行数据查询、计算、生成、审批、提醒或外部系统提交。"
    "当前只识别本次明确提出的任务，下个月、下一阶段以及未来规划中的事项都不要纳入本次任务。"
    "所有结果都要保留来源、时间、范围、口径和不确定性说明，便于后续人工确认。"
) * 3

VERY_LONG_BACKGROUND = (
    "需要记录每个字段的定义、数据类型、单位、来源、更新时间、校验状态、缺失情况和备注。"
    "相同字段按统一命名展示，保留原始精度，日期统一使用年-月-日格式，金额保留两位小数。"
    "跨区域、跨周期的记录需要注明归属，空值、重复值和异常值都要单独标记。"
    "说明内容按范围、口径、限制条件和待确认事项组织，不能把背景信息误认为新的业务任务。"
) * 70


CASES: list[dict[str, Any]] = [
    {
        "id": "LONG-TEXT-EXPLICIT-001",
        "category": "explicit_request_sentences",
        "text": (
            "请获取本季度华东和华南区域的订单、回款和客户投诉数据。"
            "请按区域和客户等级汇总订单数量、回款金额和投诉数量。"
            "请筛选逾期超过45天且尚未回款的客户。"
            "请按照逾期天数从高到低排序筛选结果。"
            "请分析华南区域投诉上升的主要原因。"
            "请比较本季度与上季度的收入变化。"
            "请预测下季度收入和利润。"
            "请生成一份经营分析报告。"
            "请输出为Word文档，并包含管理层摘要、区域对比、风险清单和整改建议。"
            "不要创建提醒，不要发起审批，不要向外部系统提交数据。"
            "下个月再考虑建立库存预警和自动提交审批流程，这些未来事项不属于本次任务。"
            + BACKGROUND
        ),
    },
    {
        "id": "LONG-TEXT-NARRATIVE-002",
        "category": "natural_narrative",
        "text": (
            "这次要围绕本季度华东和华南经营情况形成一份完整的分析任务清单。"
            "先从ERP中获取订单、回款和客户投诉明细，时间范围限定为2026年第二季度，"
            "再按区域和客户等级汇总订单数量、回款金额以及投诉数量。"
            "在汇总之后筛选逾期超过45天且尚未回款的客户，并按照逾期天数从高到低排序。"
            "随后分析华南区域投诉上升的主要原因，比较本季度与上季度的收入变化，"
            "同时预测下季度收入和利润。"
            "最后基于分析结果生成经营分析报告，包含管理层摘要、区域对比、风险清单和整改建议，"
            "输出格式可以是Word文档。"
            "本轮只需要识别任务，不要创建提醒，不要发起审批，不要向外部系统提交数据，"
            "下个月再考虑库存预警和自动提交审批流程。"
            + BACKGROUND
        ),
    },
    {
        "id": "LONG-TEXT-VERY-LONG-003",
        "category": "very_long_chunked_text",
        "text": (
            "请获取本季度华东和华南区域的订单、回款和客户投诉数据。"
            "请按区域和客户等级汇总订单数量、回款金额和投诉数量。"
            "请筛选逾期超过45天且尚未回款的客户。"
            "请按照逾期天数从高到低排序筛选结果。"
            "请分析华南区域投诉上升的主要原因。"
            "请预测下季度收入和利润。"
            "请生成一份经营分析报告。"
            "不要创建提醒，不要发起审批，不要向外部系统提交数据。"
            "下个月再考虑建立库存预警和自动提交审批流程，这些未来事项不属于本次任务。"
            + VERY_LONG_BACKGROUND
        ),
    },
]


def _level3_status(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("result"):
            return "returned"
        return "attempted_or_rejected"
    if isinstance(value, list):
        return f"called_for_{len(value)}_segments"
    return "not_triggered"


def _segment_debug(index: int, entry: dict[str, Any]) -> dict[str, Any]:
    segment = entry.get("segment") or {}
    debug = entry.get("debug") or {}
    level1 = debug.get("level1_rule_result") or {}
    level2 = debug.get("level2_semantic_result") or {}
    partial = debug.get("partial_coverage")
    return {
        "index": index,
        "text": segment.get("text"),
        "selected_by": (debug.get("final_decision") or {}).get("selected_by"),
        "l1": {
            "matched": bool(level1.get("matched")),
            "rule": level1.get("rule"),
        },
        "l2": {
            "matched": bool(level2.get("matched")),
            "skipped_reason": level2.get("skipped_reason"),
            "top_candidates": level2.get("top_candidates", [])[:3],
        },
        "l3": _level3_status(debug.get("level3_result")),
        "partial_coverage": (
            {
                "coverage_rate": partial.get("coverage_rate"),
                "uncovered_segment_count": partial.get("uncovered_segment_count"),
                "llm_called": partial.get("llm_called"),
                "l3_compensation_success": partial.get("l3_compensation_success"),
            }
            if isinstance(partial, dict)
            else None
        ),
    }


def run_case(analyzer: Any, case: dict[str, Any]) -> dict[str, Any]:
    layer = ConversationUnderstandingLayer(analyzer)
    analysis = layer.analyze_with_debug(
        text=case["text"],
        user_id="long-text-test-user",
        conversation_id=case["id"],
    )
    result = analysis.result
    debug = analysis.debug
    extraction = debug.get("long_context_extraction") or {}
    segments = [
        _segment_debug(index, entry)
        for index, entry in enumerate(debug.get("segment_analyses", []))
    ]
    return {
        "id": case["id"],
        "category": case["category"],
        "text_characters": len(case["text"]),
        "long_context_extraction": {
            "present": bool(debug.get("long_context_extraction")),
            "length_category": (
                (extraction.get("document") or {}).get("length_category")
                if extraction
                else None
            ),
            "chunk_count": len((extraction.get("document") or {}).get("chunks", [])),
            "unit_count": int((extraction.get("document") or {}).get("unit_count", 0)),
            "segment_count": len(extraction.get("segments", [])),
            "raw_candidate_count": len(extraction.get("raw_candidates", [])),
            "merged_candidate_count": len(extraction.get("merged_candidates", [])),
            "negated_candidate_count": len(extraction.get("negated_candidates", [])),
        },
        "implicit_task_fallback": debug.get("implicit_task_fallback"),
        "segment_count": len(segments),
        "segments": segments,
        "final": {
            "task_count": len(result.tasks),
            "task_types": [task.task_type for task in result.tasks],
            "task_descriptions": [task.task_description for task in result.tasks],
            "clarification_required": result.clarification_required,
            "clarification_questions": result.clarification_questions,
            "missing_inputs": sorted(
                {
                    value
                    for task in result.tasks
                    for value in task.missing_inputs
                }
            ),
            "analysis_level": result.analysis_level,
            "overall_confidence": result.overall_confidence,
        },
    }


def main() -> int:
    analyzer = build_analyzer(
        semantic_mode="local",
        llm_mode="off",
        semantic_threshold=0.50,
    )
    report = {
        "semantic_mode": "local",
        "llm_mode": "off",
        "blind_test_used": False,
        "cases": [run_case(analyzer, case) for case in CASES],
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Report saved: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
