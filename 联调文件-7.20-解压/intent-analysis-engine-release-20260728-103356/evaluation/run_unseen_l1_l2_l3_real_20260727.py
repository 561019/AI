from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
REPORT_PATH = PROJECT_ROOT / "evaluation" / "benchmark" / "unseen_l1_l2_l3_real_report_20260727.json"

for path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evaluation_runner import LocalCapabilityVectorRepository, LocalEvaluationEmbeddingService  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services.conversation_understanding import ConversationUnderstandingLayer  # noqa: E402
from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer  # noqa: E402
from app.services.intent_analysis_engine.llm import LLMTaskAnalyzer  # noqa: E402
from app.services.model_gateway import ModelGateway  # noqa: E402
from app.services.semantic import SemanticCapabilityCatalog, SemanticMatcher  # noqa: E402


@dataclass(frozen=True)
class Case:
    case_id: str
    group: str
    text: str
    expected_tasks: list[str]
    should_clarify: bool
    mode: str = "direct"
    expected_source: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)


class AuditedGateway:
    def __init__(self) -> None:
        self.inner = ModelGateway(timeout=90, retry_backoff_seconds=())
        self.calls: list[dict[str, Any]] = []

    def analyze(self, messages: list[dict[str, str]], response_schema: dict[str, Any] | None = None) -> Any:
        response = self.inner.analyze(messages=messages, response_schema=response_schema)
        self.calls.append(
            {
                "provider": response.provider,
                "model": response.model,
                "request_id": response.request_id,
                "elapsed_ms": response.elapsed_ms,
                "retry_count": response.retry_count,
                "fallback_used": response.fallback_used,
                "fallback_provider": response.fallback_provider,
                "error": response.error,
            }
        )
        return response


CASES: list[Case] = [
    Case(
        "UNSEEN-L1-001",
        "l1_rule",
        "请按2026年新版提成口径核算华东销售团队上月提成",
        ["RULE_CALCULATION_COMMISSION"],
        False,
        expected_source="rule",
    ),
    Case("UNSEEN-L1-002", "l1_rule", "把逾期60天仍未回款的客户筛出来", ["DATA_FILTER"], False, expected_source="rule"),
    Case("UNSEEN-L1-003", "l1_rule", "按逾期天数从高到低排一下这些客户", ["DATA_SORT"], False, expected_source="rule"),
    Case("UNSEEN-L1-004", "l1_rule", "分析华南投诉量突然上升的原因", ["DATA_ANALYSIS_PROBLEM"], False, expected_source="rule"),
    Case("UNSEEN-L1-005", "l1_rule", "预测三季度门店收入走势", ["DATA_ANALYSIS_FORECAST"], False, expected_source="rule"),
    Case("UNSEEN-L1-006", "l1_rule", "和去年同期对比一下本月回款金额", ["DATA_ANALYSIS_YOY"], False, expected_source="rule"),
    Case("UNSEEN-L1-007", "l1_rule", "和上个月比一下本周订单量变化", ["DATA_ANALYSIS_MOM"], False, expected_source="rule"),
    Case("UNSEEN-L1-008", "l1_rule", "生成一份渠道经营复盘报告", ["DOCUMENT_GENERATE"], False, expected_source="rule"),
    Case("UNSEEN-L1-009", "l1_rule", "写一封通知，让各区域周五前提交预算说明", ["CONTENT_GENERATE"], False, expected_source="rule"),
    Case("UNSEEN-L1-010", "l1_rule", "做一张新品发布海报", ["MULTIMEDIA_GENERATE"], False, expected_source="rule"),
    Case("UNSEEN-L1-011", "l1_rule", "启动供应商准入流程", ["WORKFLOW_START"], False, expected_source="rule"),
    Case("UNSEEN-L1-012", "l1_rule", "库存低于安全线时提醒运营负责人", ["MONITORING_REMINDER"], False, expected_source="rule"),
    Case("UNSEEN-L1-013", "l1_rule", "根据本月提成结果生成一张计提凭证", ["DIGITAL_ASSET_ACCRUAL_VOUCHER"], False, expected_source="rule"),
    Case("UNSEEN-L1-014", "l1_rule", "读取这份合同PDF里的付款表格", ["DOCUMENT_TABLE_PARSE"], False, expected_source="rule"),
    Case("UNSEEN-L1-015", "l1_rule", "提取这个Excel模板的字段结构", ["FILE_STRUCTURE_EXTRACT"], False, expected_source="rule"),
    Case("UNSEEN-L2-001", "l2_semantic", "客户清单帮我调出来看看", ["DATA_QUERY_FETCH"], True, expected_source="semantic"),
    Case("UNSEEN-L2-002", "l2_semantic", "费用总额", ["DATA_AGGREGATION_SUMMARY"], True, expected_source="semantic"),
    Case("UNSEEN-L2-003", "l2_semantic", "供应商准入审批", ["WORKFLOW_START"], False, expected_source="semantic"),
    Case("UNSEEN-L2-004", "l2_semantic", "回款政策", ["QUESTION_ANSWER"], False, expected_source="semantic"),
    Case("UNSEEN-L2-005", "l2_semantic", "本月回款明细", ["DATA_QUERY_FETCH"], True, expected_source="semantic"),
    Case("UNSEEN-L2-006", "l2_semantic", "经营复盘材料", ["DOCUMENT_GENERATE"], False, expected_source="semantic"),
    Case("UNSEEN-L2-007", "l2_semantic", "门店营业额周报", ["DOCUMENT_GENERATE"], False, expected_source="semantic"),
    Case("UNSEEN-L2-008", "l2_semantic", "客户流失风险清单", ["DATA_FILTER"], False, expected_source="semantic"),
    Case("UNSEEN-L2-009", "l2_semantic", "渠道投入复盘", ["DATA_ANALYSIS_PROBLEM"], False, expected_source="semantic"),
    Case("UNSEEN-L2-010", "l2_semantic", "供应链周转情况", ["DATA_ANALYSIS_PROBLEM"], False, expected_source="semantic"),
    Case("UNSEEN-L3-001", "l3_real_model", "需要判断客户经营质量有没有明显下滑信号", ["DATA_ANALYSIS_PROBLEM"], False, expected_source="llm"),
    Case("UNSEEN-L3-002", "l3_real_model", "盘一下渠道投入是否值得继续加码", ["DATA_ANALYSIS_PROBLEM"], False, expected_source="llm"),
    Case("UNSEEN-L3-003", "l3_real_model", "Please create an operating review report for Q2 regional sales", ["DOCUMENT_GENERATE"], False, expected_source="llm"),
    Case(
        "UNSEEN-L3-004",
        "l3_real_model",
        "Need a task list: retrieve CRM accounts, rank risk, and draft remediation plan",
        ["EXTERNAL_DATA_FETCH", "DATA_SORT", "IMPROVEMENT_PLAN_GENERATE"],
        False,
        expected_source="llm",
    ),
    Case("UNSEEN-L3-005", "l3_real_model", "对这批回款线索给一个经营处置判断", ["DATA_ANALYSIS_PROBLEM"], False, expected_source="llm"),
    Case("UNSEEN-L3-006", "l3_real_model", "Turn the renewal health notes into a manager-ready review memo", ["DOCUMENT_GENERATE"], False, expected_source="llm"),
    Case("UNSEEN-L3-007", "l3_real_model", "Find signals that partner enablement is no longer producing enough qualified leads", ["DATA_ANALYSIS_PROBLEM"], False, expected_source="llm"),
    Case(
        "UNSEEN-L3-008",
        "l3_real_model",
        "I need the customer renewal dataset pulled from CRM and summarized by risk tier",
        ["EXTERNAL_DATA_FETCH", "DATA_AGGREGATION_SUMMARY"],
        False,
        expected_source="llm",
    ),
    Case(
        "UNSEEN-CTX-001",
        "context_ellipsis",
        "换个口径再算一遍",
        ["RULE_CALCULATION_COMMISSION"],
        True,
        mode="conversation",
        expected_source="context_recovery",
        history=[{"role": "user", "text": "请先核算华东上月销售提成。"}],
    ),
    Case(
        "UNSEEN-CTX-002",
        "context_ellipsis",
        "接着润色一下",
        ["DOCUMENT_GENERATE"],
        False,
        mode="conversation",
        expected_source="context_recovery",
        history=[{"role": "user", "text": "帮我生成一份渠道经营复盘报告。"}],
    ),
    Case(
        "UNSEEN-CTX-003",
        "context_ambiguous",
        "接着处理",
        [],
        True,
        mode="conversation",
        expected_source="clarification",
        history=[
            {"role": "user", "text": "查询本月库存明细。"},
            {"role": "user", "text": "分析销售下滑原因。"},
        ],
    ),
    Case("UNSEEN-CTX-004", "context_missing", "重新看看", [], True, mode="conversation", expected_source="clarification"),
    Case(
        "UNSEEN-CTX-005",
        "context_override",
        "不用了，改成生成客户续约周报",
        ["DOCUMENT_GENERATE"],
        False,
        mode="conversation",
        expected_source="rule",
        history=[{"role": "user", "text": "先核算销售提成。"}],
    ),
    Case(
        "UNSEEN-LONG-001",
        "long_text",
        (
            "这次只需要输出任务清单，不要执行。请先从CRM拉取2026年二季度华东和华南重点客户、订单、回款、投诉明细；"
            "按区域和客户等级统计订单数量、回款金额、投诉数量；筛出逾期超过45天且仍未回款的客户；"
            "按逾期天数从高到低排序；分析华南投诉增长原因；和上季度比较收入变化；预测下季度收入和利润；"
            "最后生成经营复盘报告，报告包含风险清单和整改建议。不要创建提醒，不要发起审批，不要提交到OA。"
            "下个月再考虑库存预警和自动审批，这些不属于本次任务。"
            + "背景说明：所有字段保留来源、口径、时间范围和不确定性说明，不要把背景说明识别成新任务。" * 30
        ),
        [
            "EXTERNAL_DATA_FETCH",
            "DATA_AGGREGATION_SUMMARY",
            "DATA_FILTER",
            "DATA_SORT",
            "DATA_ANALYSIS_PROBLEM",
            "DATA_ANALYSIS_MOM",
            "DATA_ANALYSIS_FORECAST",
            "DOCUMENT_GENERATE",
        ],
        False,
        mode="long_text",
    ),
    Case(
        "UNSEEN-LONG-002",
        "long_text",
        (
            "我们要复盘渠道健康度，先把各渠道线索、成交、退单和回款数据拿出来；"
            "再做一个可行动的判断：哪些渠道投入产出不合理，为什么变差；"
            "需要把可疑客户群单独圈出来，后面按风险高低排；最后形成一页管理层材料。"
            "不要安排提醒，也不用进OA。下周可能要做自动审批，但这不是今天的任务。"
            + "补充背景：本段只是业务口径和数据质量要求，需要保留字段定义、来源和备注。" * 25
        ),
        ["DATA_QUERY_FETCH", "DATA_ANALYSIS_PROBLEM", "DATA_FILTER", "DATA_SORT", "DOCUMENT_GENERATE"],
        False,
        mode="long_text",
    ),
    Case(
        "UNSEEN-LONG-003",
        "long_text",
        (
            "请把本年度各门店会员续约、到店频次、客诉和退款数据整理成任务清单：先获取明细，"
            "再按城市和会员等级汇总续约率、退款金额和客诉数量，筛出续约率低于目标且退款金额异常的门店，"
            "按退款金额倒序排序，分析低续约门店的共同原因，并生成会员经营复盘报告。"
            "不要创建监控提醒，不要提交审批，也不要把明年计划中的自动预警算进本次任务。"
            + "数据治理说明：重复记录、空值、跨区域归属和口径冲突都只作为说明保留。" * 80
        ),
        [
            "DATA_QUERY_FETCH",
            "DATA_AGGREGATION_SUMMARY",
            "DATA_FILTER",
            "DATA_SORT",
            "DATA_ANALYSIS_PROBLEM",
            "DOCUMENT_GENERATE",
        ],
        False,
        mode="long_text",
    ),
]


def build_runtime() -> tuple[StandardIntentAnalyzer, ConversationUnderstandingLayer, AuditedGateway]:
    registry = FunctionRegistryCatalog()
    capability_catalog = SemanticCapabilityCatalog.from_default_file()
    embedding_service = LocalEvaluationEmbeddingService()
    semantic_matcher = SemanticMatcher(
        embedding_service=embedding_service,
        vector_repository=LocalCapabilityVectorRepository(
            embedding_service=embedding_service,
            capability_catalog=capability_catalog,
        ),
        registry=registry,
        capability_catalog=capability_catalog,
        match_threshold=0.50,
    )
    gateway = AuditedGateway()
    llm_analyzer = LLMTaskAnalyzer(model_gateway=gateway, registry=registry)
    analyzer = StandardIntentAnalyzer(
        registry=registry,
        semantic_matcher=semantic_matcher,
        llm_analyzer=llm_analyzer,
        intent_record_service=None,
        semantic_threshold=0.50,
    )
    layer = ConversationUnderstandingLayer(analyzer, implicit_fallback_batch_characters=4000)
    return analyzer, layer, gateway


def main() -> int:
    _configure_stdout()
    analyzer, layer, gateway = build_runtime()
    rows = []
    for case in CASES:
        before_calls = len(gateway.calls)
        if case.mode == "direct":
            analysis = analyzer.analyze_with_debug(
                text=case.text,
                user_id="unseen-real-test",
                conversation_id=case.case_id,
            )
        else:
            analysis = layer.analyze_with_debug(
                text=case.text,
                user_id="unseen-real-test",
                conversation_id=case.case_id,
                history=case.history,
            )
        llm_calls = gateway.calls[before_calls:]
        rows.append(make_row(case, analysis.result, analysis.debug, llm_calls))

    report = summarize(rows)
    report["version_info"] = version_info()
    report["sample_duplicate_check"] = duplicate_check()
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_report(report)
    return 0


def make_row(case: Case, result: Any, debug: dict[str, Any], llm_calls: list[dict[str, Any]]) -> dict[str, Any]:
    actual_tasks = [task.task_type for task in result.tasks]
    expected_tasks = case.expected_tasks
    expected_set = set(expected_tasks)
    actual_set = set(actual_tasks)
    exact_task_pass = actual_tasks == expected_tasks
    set_task_pass = expected_set == actual_set
    clarification_pass = bool(result.clarification_required) == case.should_clarify
    source_pass = source_matches(case.expected_source, debug, llm_calls)
    row = {
        "id": case.case_id,
        "group": case.group,
        "mode": case.mode,
        "text": case.text,
        "text_characters": len(case.text),
        "expected_tasks": expected_tasks,
        "actual_tasks": actual_tasks,
        "expected_clarification": case.should_clarify,
        "actual_clarification": bool(result.clarification_required),
        "expected_source": case.expected_source,
        "selected_by": selected_by(debug),
        "trigger_trace": trigger_trace(debug),
        "llm_call_count": len(llm_calls),
        "llm_fallback_count": sum(1 for call in llm_calls if call.get("fallback_used")),
        "llm_calls": llm_calls,
        "missing_inputs": [task.missing_inputs for task in result.tasks],
        "clarification_questions": result.clarification_questions,
        "analysis_level": result.analysis_level,
        "long_text_debug": long_text_debug(debug),
        "exact_task_pass": exact_task_pass,
        "set_task_pass": set_task_pass,
        "clarification_pass": clarification_pass,
        "source_pass": source_pass,
        "task_precision": len(expected_set & actual_set) / len(actual_set) if actual_set else (1.0 if not expected_set else 0.0),
        "task_recall": len(expected_set & actual_set) / len(expected_set) if expected_set else (1.0 if not actual_set else 0.0),
    }
    row["passed"] = row["set_task_pass"] and row["clarification_pass"] and row["source_pass"]
    return row


def selected_by(debug: dict[str, Any]) -> str | None:
    decision = debug.get("final_decision")
    if isinstance(decision, dict):
        value = decision.get("selected_by")
        return str(value) if value is not None else None
    return None


def source_matches(expected_source: str | None, debug: dict[str, Any], llm_calls: list[dict[str, Any]]) -> bool:
    if expected_source is None:
        return True
    selected = selected_by(debug)
    if expected_source == "llm":
        return bool(llm_calls) and not any(call.get("fallback_used") for call in llm_calls)
    if expected_source == "clarification":
        return selected in {"clarification_gate", "fallback", None} or (
            not bool(debug.get("final_tasklist", {}).get("tasks")) if isinstance(debug.get("final_tasklist"), dict) else False
        )
    return selected == expected_source


def trigger_trace(debug: dict[str, Any]) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    segment_entries = debug.get("segment_analyses")
    if isinstance(segment_entries, list) and segment_entries:
        for index, entry in enumerate(segment_entries):
            if not isinstance(entry, dict):
                continue
            segment = entry.get("segment") if isinstance(entry.get("segment"), dict) else {}
            segment_debug = entry.get("debug") if isinstance(entry.get("debug"), dict) else {}
            traces.append(single_trace(segment_debug, index=index, text=str(segment.get("text") or "")))
        return traces
    return [single_trace(debug, index=0, text="")]


def single_trace(debug: dict[str, Any], *, index: int, text: str) -> dict[str, Any]:
    level1 = debug.get("level1_rule_result") if isinstance(debug.get("level1_rule_result"), dict) else {}
    level2 = debug.get("level2_semantic_result") if isinstance(debug.get("level2_semantic_result"), dict) else {}
    level3 = debug.get("level3_result")
    return {
        "segment_index": index,
        "text": text,
        "selected_by": selected_by(debug),
        "l1_matched": bool(level1.get("matched")),
        "l1_rule": level1.get("rule"),
        "l2_matched": bool(level2.get("matched")),
        "l2_confidence": level2.get("confidence"),
        "l2_top_candidates": level2.get("top_candidates", [])[:3],
        "l3_debug_present": level3 is not None,
        "partial_coverage": debug.get("partial_coverage"),
    }


def long_text_debug(debug: dict[str, Any]) -> dict[str, Any] | None:
    extraction = debug.get("long_context_extraction")
    if not isinstance(extraction, dict):
        return None
    document = extraction.get("document") if isinstance(extraction.get("document"), dict) else {}
    return {
        "length_category": document.get("length_category"),
        "character_count": document.get("character_count"),
        "chunk_count": len(document.get("chunks", [])) if isinstance(document.get("chunks"), list) else 0,
        "unit_count": document.get("unit_count"),
        "segment_count": len(extraction.get("segments", [])) if isinstance(extraction.get("segments"), list) else 0,
        "raw_candidate_count": len(extraction.get("raw_candidates", [])) if isinstance(extraction.get("raw_candidates"), list) else 0,
        "merged_candidate_count": len(extraction.get("merged_candidates", [])) if isinstance(extraction.get("merged_candidates"), list) else 0,
        "negated_candidate_count": len(extraction.get("negated_candidates", [])) if isinstance(extraction.get("negated_candidates"), list) else 0,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected_empty = [row for row in rows if not row["expected_tasks"]]
    actual_empty_false_positive = [row for row in expected_empty if row["actual_tasks"]]
    l3_expected = [row for row in rows if row["expected_source"] == "llm"]
    trigger_counter = Counter()
    for row in rows:
        for trace in row["trigger_trace"]:
            trigger_counter[str(trace.get("selected_by") or "unknown")] += 1
    return {
        "total": len(rows),
        "passed_cases": sum(1 for row in rows if row["passed"]),
        "full_pass_rate": ratio(rows, "passed"),
        "task_type_exact_accuracy": ratio(rows, "exact_task_pass"),
        "task_type_set_accuracy": ratio(rows, "set_task_pass"),
        "task_type_set_precision": average(rows, "task_precision"),
        "task_type_set_recall": average(rows, "task_recall"),
        "clarification_accuracy": ratio(rows, "clarification_pass"),
        "source_accuracy": ratio(rows, "source_pass"),
        "false_positive_rate_on_no_task_cases": len(actual_empty_false_positive) / len(expected_empty) if expected_empty else 0.0,
        "false_positive_count_on_no_task_cases": len(actual_empty_false_positive),
        "no_task_case_count": len(expected_empty),
        "l3_expected_case_count": len(l3_expected),
        "l3_real_call_pass_rate": ratio(l3_expected, "source_pass"),
        "llm_total_call_count": sum(row["llm_call_count"] for row in rows),
        "llm_fallback_total_count": sum(row["llm_fallback_count"] for row in rows),
        "trigger_counts": dict(sorted(trigger_counter.items())),
        "by_group": {
            group: summarize_subset(items)
            for group, items in sorted(group_by(rows, "group").items())
        },
        "failed_cases": [row for row in rows if not row["passed"]],
        "rows": rows,
    }


def summarize_subset(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(rows),
        "passed_cases": sum(1 for row in rows if row["passed"]),
        "full_pass_rate": ratio(rows, "passed"),
        "task_type_set_accuracy": ratio(rows, "set_task_pass"),
        "task_type_set_precision": average(rows, "task_precision"),
        "task_type_set_recall": average(rows, "task_recall"),
        "clarification_accuracy": ratio(rows, "clarification_pass"),
        "source_accuracy": ratio(rows, "source_pass"),
        "llm_call_count": sum(row["llm_call_count"] for row in rows),
        "llm_fallback_count": sum(row["llm_fallback_count"] for row in rows),
    }


def ratio(rows: list[dict[str, Any]], field: str) -> float:
    return sum(1 for row in rows if row[field]) / len(rows) if rows else 0.0


def average(rows: list[dict[str, Any]], field: str) -> float:
    return sum(float(row[field]) for row in rows) / len(rows) if rows else 0.0


def group_by(rows: list[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row[field]), []).append(row)
    return grouped


def version_info() -> dict[str, Any]:
    return {
        "blind_test_used": False,
        "semantic_mode": "local",
        "semantic_threshold": 0.50,
        "llm_provider": settings.llm_provider,
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
        "llm_api_key_configured": bool(settings.llm_api_key),
        "tasklist_schema_changed": False,
        "prompt_changed_by_this_script": False,
    }


def duplicate_check() -> dict[str, Any]:
    known_texts = load_non_blind_known_texts()
    sample_texts = [case.text for case in CASES]
    for case in CASES:
        sample_texts.extend(str(item.get("text") or "") for item in case.history)
    duplicates = sorted(text for text in sample_texts if text and text in known_texts)
    return {
        "blind_test_used": False,
        "skipped_any_path_containing_blind": True,
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
        if "blind" in path.as_posix().lower() or not path.exists():
            continue
        try:
            if path.suffix == ".jsonl":
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        collect_texts(json.loads(line), texts)
            else:
                collect_texts(json.loads(path.read_text(encoding="utf-8")), texts)
        except Exception:
            continue
    return texts


def collect_texts(value: Any, texts: set[str]) -> None:
    if isinstance(value, dict):
        for key in ("text", "input", "user_input"):
            text = value.get(key)
            if isinstance(text, str):
                texts.add(text)
        for key in ("conversation", "history", "messages"):
            nested = value.get(key)
            if isinstance(nested, list):
                for item in nested:
                    collect_texts(item, texts)
    elif isinstance(value, list):
        for item in value:
            collect_texts(item, texts)


def print_report(report: dict[str, Any]) -> None:
    print(f"Report saved: {REPORT_PATH.relative_to(PROJECT_ROOT)}")
    print(f"Total cases: {report['total']}")
    print(f"Full pass: {report['passed_cases']}/{report['total']} = {report['full_pass_rate']:.2%}")
    print(f"Task type set accuracy: {report['task_type_set_accuracy']:.2%}")
    print(f"Task type set precision: {report['task_type_set_precision']:.2%}")
    print(f"Task type set recall: {report['task_type_set_recall']:.2%}")
    print(f"Clarification accuracy: {report['clarification_accuracy']:.2%}")
    print(f"Source accuracy: {report['source_accuracy']:.2%}")
    print(f"L3 real call pass: {report['l3_real_call_pass_rate']:.2%}")
    print(f"LLM calls: {report['llm_total_call_count']}, fallback: {report['llm_fallback_total_count']}")
    print(f"Exact duplicate count against non-blind datasets: {report['sample_duplicate_check']['exact_duplicate_count']}")
    print("By group:")
    for group, item in report["by_group"].items():
        print(
            f"- {group}: pass={item['passed_cases']}/{item['total']} ({item['full_pass_rate']:.2%}), "
            f"task_set={item['task_type_set_accuracy']:.2%}, clarify={item['clarification_accuracy']:.2%}, "
            f"source={item['source_accuracy']:.2%}, llm_calls={item['llm_call_count']}, fallback={item['llm_fallback_count']}"
        )
    print("Failed cases:")
    for row in report["failed_cases"]:
        failed_parts = [
            name
            for name, ok in (
                ("task", row["set_task_pass"]),
                ("clarification", row["clarification_pass"]),
                ("source", row["source_pass"]),
            )
            if not ok
        ]
        print(f"- {row['id']} [{row['group']}] failed={','.join(failed_parts)}")
        print(f"  text={row['text'][:160]}")
        print(f"  expected={row['expected_tasks']} clarify={row['expected_clarification']} source={row['expected_source']}")
        print(f"  actual  ={row['actual_tasks']} clarify={row['actual_clarification']} selected={row['selected_by']} llm_calls={row['llm_call_count']} fallback={row['llm_fallback_count']}")


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
