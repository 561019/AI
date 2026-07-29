from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATASET_ROOT = ROOT / "datasets"
CATEGORY_SIZE = 30


def main() -> int:
    cases = []
    for category, builder in CATEGORY_BUILDERS:
        built = builder()
        if len(built) != CATEGORY_SIZE:
            raise ValueError(f"{category} must contain {CATEGORY_SIZE} cases, got {len(built)}")
        cases.extend(_with_category(category, built))

    split_cases = {"train": [], "validation": [], "blind_test": []}
    counters = {key: 1 for key in split_cases}
    per_category_index: dict[str, int] = {}
    for case in cases:
        category = case["intent_category"]
        index = per_category_index.get(category, 0)
        per_category_index[category] = index + 1
        split = "train" if index < 18 else "validation" if index < 24 else "blind_test"
        case["id"] = f"BENCH-{split.upper()}-{counters[split]:03d}"
        counters[split] += 1
        split_cases[split].append(case)

    for split, items in split_cases.items():
        path = DATASET_ROOT / split / f"{split}_v1.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n",
            encoding="utf-8",
        )

    manifest = {
        "version": "v1",
        "description": "De-identified enterprise-style blind benchmark seed dataset for Intent Analysis Engine.",
        "total": len(cases),
        "splits": {split: len(items) for split, items in split_cases.items()},
        "categories": {
            category: CATEGORY_SIZE
            for category, _ in CATEGORY_BUILDERS
        },
        "blind_test_policy": "Do not inspect or use blind_test cases for rule, prompt, threshold, or model development. Runner requires --allow-blind-test.",
        "sample_required_fields": [
            "id",
            "text",
            "intent_category",
            "expected_tasks",
            "expected_task_types",
            "required_clarification",
            "missing_inputs",
            "forbidden_tasks",
        ],
        "optional_fields": [
            "history",
            "context",
            "notes",
        ],
    }
    (DATASET_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


def _with_category(category: str, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": "",
            "text": spec["text"],
            "intent_category": category,
            "expected_tasks": [
                {"task_type": task_type}
                for task_type in spec.get("expected_task_types", [])
            ],
            "expected_task_types": spec.get("expected_task_types", []),
            "required_clarification": spec.get("required_clarification", False),
            "missing_inputs": spec.get("missing_inputs", []),
            "forbidden_tasks": spec.get("forbidden_tasks", []),
            **({"history": spec["history"]} if "history" in spec else {}),
            **({"context": spec["context"]} if "context" in spec else {}),
            **({"notes": spec["notes"]} if "notes" in spec else {}),
        }
        for spec in specs
    ]


def c(
    text: str,
    task_types: list[str] | None = None,
    *,
    clarify: bool = False,
    missing: list[str] | None = None,
    forbidden: list[str] | None = None,
    history: list[dict[str, str]] | None = None,
    context: dict[str, Any] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    return {
        "text": text,
        "expected_task_types": task_types or [],
        "required_clarification": clarify,
        "missing_inputs": missing or [],
        "forbidden_tasks": forbidden or [],
        **({"history": history} if history is not None else {}),
        **({"context": context} if context is not None else {}),
        **({"notes": notes} if notes is not None else {}),
    }


def build_short_instruction() -> list[dict[str, Any]]:
    return [
        c("解析这份销售明细Excel", ["DOCUMENT_TABLE_PARSE"]),
        c("提取合同附件里的字段结构", ["FILE_STRUCTURE_EXTRACT"]),
        c("从CRM获取客户名单", ["EXTERNAL_DATA_FETCH"]),
        c("把审批结果回传到OA", ["EXTERNAL_SYSTEM_SUBMIT"]),
        c("查询本月销售明细", ["DATA_QUERY_FETCH"]),
        c("统计各区域销售额", ["DATA_AGGREGATION_SUMMARY"]),
        c("按产品分类求和销售金额", ["DATA_ANALYSIS_GROUP_SUM"]),
        c("生成销售数据透视表", ["DATA_ANALYSIS_PIVOT"]),
        c("筛选逾期未回款客户", ["DATA_FILTER"]),
        c("按销售额排名客户", ["DATA_SORT"]),
        c("整理客户投诉记录", ["COMPLAINT_INFORMATION_ORGANIZE"]),
        c("根据公式计算费用", ["RULE_CALCULATION_GENERAL"], clarify=True, missing=["calculation_basis"]),
        c("计算销售提成", ["RULE_CALCULATION_COMMISSION"], clarify=True, missing=["calculation_policy", "sales_data_source"]),
        c("分析收入下降原因", ["DATA_ANALYSIS_PROBLEM"]),
        c("分析本月销售额同比变化", ["DATA_ANALYSIS_YOY"]),
        c("分析本周订单环比变化", ["DATA_ANALYSIS_MOM"]),
        c("预测下季度销售额趋势", ["DATA_ANALYSIS_FORECAST"]),
        c("公司的报销政策是什么", ["QUESTION_ANSWER"]),
        c("生成经营分析报告", ["DOCUMENT_GENERATE"]),
        c("起草客户说明邮件", ["CONTENT_GENERATE"]),
        c("生成客户投诉改进方案", ["IMPROVEMENT_PLAN_GENERATE"]),
        c("生成一张新品海报", ["MULTIMEDIA_GENERATE"]),
        c("办理报销流程", ["PROCESS_HANDLE"]),
        c("发起采购审批流程", ["WORKFLOW_START"]),
        c("库存低于100时提醒我", ["MONITORING_REMINDER"]),
        c("根据提成结果生成计提凭证", ["DIGITAL_ASSET_ACCRUAL_VOUCHER"]),
        c("查看上个月订单明细", ["DATA_QUERY_FETCH"]),
        c("汇总本季度费用金额", ["DATA_AGGREGATION_SUMMARY"]),
        c("过滤无效客户记录", ["DATA_FILTER"]),
        c("写一份会议通知", ["CONTENT_GENERATE"]),
    ]


def build_long_requirement() -> list[dict[str, Any]]:
    subjects = [
        ("销售经营", "销售数据", "销售下降原因", "经营分析报告"),
        ("回款管理", "回款明细", "逾期原因", "回款分析材料"),
        ("客户运营", "客户资料", "客户流失原因", "客户维护方案"),
        ("库存管理", "库存记录", "库存异常原因", "库存预警报告"),
        ("费用管控", "费用明细", "费用波动原因", "费用分析文档"),
    ]
    cases = []
    for topic, data_object, reason, output in subjects:
        cases.extend(
            [
                c(
                    f"为了月度复盘，先整理本月{data_object}，再分析{reason}，最后生成{output}。",
                    ["DATA_QUERY_FETCH", "DATA_ANALYSIS_PROBLEM", "DOCUMENT_GENERATE"],
                ),
                c(
                    f"会议背景里提到{topic}压力较大，当前明确要求是统计本季度{data_object}，按区域排序，并预测下季度趋势。",
                    ["DATA_AGGREGATION_SUMMARY", "DATA_SORT", "DATA_ANALYSIS_FORECAST"],
                    clarify=True,
                    missing=["summary_field"],
                ),
                c(
                    f"我们暂时不做自动提醒，先从业务系统获取{data_object}，筛选异常记录，形成给管理层看的材料。",
                    ["EXTERNAL_DATA_FETCH", "DATA_FILTER", "DOCUMENT_GENERATE"],
                    forbidden=["MONITORING_REMINDER"],
                ),
                c(
                    f"这段是项目背景说明，不构成任务。真正要处理的是解析上传附件中的{data_object}，提取字段结构，并汇总关键金额。",
                    ["DOCUMENT_TABLE_PARSE", "FILE_STRUCTURE_EXTRACT", "DATA_AGGREGATION_SUMMARY"],
                    clarify=True,
                    missing=["statistical_range"],
                ),
                c(
                    f"领导希望复盘{topic}，需要了解相关制度口径，然后分析{reason}，输出一份改进方案。",
                    ["QUESTION_ANSWER", "DATA_ANALYSIS_PROBLEM", "IMPROVEMENT_PLAN_GENERATE"],
                ),
                c(
                    f"本次材料只用于内部评审，请查询去年{data_object}，做同比分析，再生成正式报告。",
                    ["DATA_QUERY_FETCH", "DATA_ANALYSIS_YOY", "DOCUMENT_GENERATE"],
                ),
            ]
        )
    return cases[:CATEGORY_SIZE]


def build_colloquial_expression() -> list[dict[str, Any]]:
    return [
        c("帮我瞅瞅今年销售咋样", ["DATA_ANALYSIS_PROBLEM"]),
        c("把上月各区的数捋一遍", ["DATA_AGGREGATION_SUMMARY"], clarify=True, missing=["summary_field"]),
        c("销售提成给算一下", ["RULE_CALCULATION_COMMISSION"], clarify=True, missing=["calculation_policy", "sales_data_source"]),
        c("给老板弄一份经营汇报", ["DOCUMENT_GENERATE"]),
        c("看看库存有没有啥问题", ["DATA_ANALYSIS_PROBLEM"]),
        c("CRM里的客户名单给我调出来", ["EXTERNAL_DATA_FETCH"]),
        c("这张表帮我读一下", ["DOCUMENT_TABLE_PARSE"], clarify=True, missing=["file"]),
        c("给我整张新品海报", ["MULTIMEDIA_GENERATE"]),
        c("采购审批帮我走一下", ["PROCESS_HANDLE"]),
        c("库存少了就吱一声", ["MONITORING_REMINDER"], clarify=True, missing=["trigger_condition"]),
        c("把费用从高到低排排", ["DATA_SORT"]),
        c("挑出那些回款晚的客户", ["DATA_FILTER"]),
        c("下季度销量估一估", ["DATA_ANALYSIS_FORECAST"]),
        c("提成政策到底咋规定的", ["QUESTION_ANSWER"]),
        c("把核算结果做成凭证", ["DIGITAL_ASSET_ACCRUAL_VOUCHER"]),
        c("这月和上月比一比销售额", ["DATA_ANALYSIS_MOM"]),
        c("帮我拉一下ERP库存", ["EXTERNAL_DATA_FETCH"]),
        c("这个PDF里的清单取出来", ["DOCUMENT_TABLE_PARSE"]),
        c("销售情况给我看一眼", ["DATA_ANALYSIS_PROBLEM"]),
        c("把投诉的事归一归类", ["COMPLAINT_INFORMATION_ORGANIZE"]),
        c("费用报销邮件帮我写一下", ["CONTENT_GENERATE"]),
        c("弄个客户维护计划", ["IMPROVEMENT_PLAN_GENERATE"]),
        c("订单金额帮我排个榜", ["DATA_SORT"]),
        c("这个制度是咋回事", ["QUESTION_ANSWER"]),
        c("上月销售额和去年比一比", ["DATA_ANALYSIS_YOY"]),
        c("低库存的商品帮我找出来", ["DATA_FILTER"]),
        c("这份附件的表头看看", ["FILE_STRUCTURE_EXTRACT"]),
        c("把客户数据拿出来", ["DATA_QUERY_FETCH"], clarify=True, missing=["data_source"]),
        c("给活动做个宣传图", ["MULTIMEDIA_GENERATE"]),
        c("把订单状态写回系统", ["EXTERNAL_SYSTEM_SUBMIT"], clarify=True, missing=["external_system"]),
    ]


def build_omitted_expression() -> list[dict[str, Any]]:
    contexts = [
        ("计算2025年销售提成", "RULE_CALCULATION_COMMISSION", "计算", "销售提成", ["帮我再算一遍", "重新算一下", "再核一遍"]),
        ("生成经营分析报告", "DOCUMENT_GENERATE", "生成", "经营分析报告", ["接着改", "继续调整一下", "再改一版"]),
        ("分析销售趋势", "DATA_ANALYSIS_PROBLEM", "分析", "销售趋势", ["换个维度看看", "再换个角度分析", "换个维度分析"]),
        ("统计本月费用金额", "DATA_AGGREGATION_SUMMARY", "统计", "费用金额", ["再按部门看", "换个部门维度", "继续按部门汇总"]),
        ("查询CRM客户资料", "EXTERNAL_DATA_FETCH", "查询", "客户资料", ["再查一遍", "帮我重新拉一下", "再取一次"]),
        ("生成客户沟通邮件", "CONTENT_GENERATE", "生成", "客户沟通邮件", ["语气再柔和点", "继续改邮件", "再写一版"]),
        ("预测下季度收入趋势", "DATA_ANALYSIS_FORECAST", "预测", "收入趋势", ["利润也预测一下", "换成利润看看", "再预测利润"]),
        ("解析销售Excel", "DOCUMENT_TABLE_PARSE", "解析", "销售Excel", ["再提取字段", "继续看结构", "字段也列一下"]),
        ("筛选高风险客户", "DATA_FILTER", "筛选", "高风险客户", ["再筛一遍", "把重点的也挑出来", "继续筛异常"]),
        ("发起采购审批流程", "WORKFLOW_START", "发起", "采购审批流程", ["再查一下进度", "继续跟进", "审批状态也看一下"]),
    ]
    cases = []
    for source_text, task_type, action, obj, utterances in contexts:
        provider_context = {
            "conversation_context": [
                {
                    "task_type": task_type,
                    "task_description": source_text,
                    "source_text": source_text,
                    "action": action,
                    "object": obj,
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
        for utterance in utterances:
            cases.append(
                c(
                    utterance,
                    [task_type if task_type not in {"WORKFLOW_START"} else "DATA_QUERY_FETCH"],
                    context=provider_context,
                    clarify=utterance in {"再查一下进度", "审批状态也看一下"},
                    missing=["data_source"] if utterance in {"再查一下进度", "审批状态也看一下"} else [],
                )
            )
    return cases[:CATEGORY_SIZE]


def build_multi_task_request() -> list[dict[str, Any]]:
    return [
        c("查询销售明细，按区域汇总，再分析下降原因", ["DATA_QUERY_FETCH", "DATA_AGGREGATION_SUMMARY", "DATA_ANALYSIS_PROBLEM"], clarify=True, missing=["statistical_range"]),
        c("拉取CRM客户资料，筛选重点客户，生成跟进话术", ["EXTERNAL_DATA_FETCH", "DATA_FILTER", "CONTENT_GENERATE"]),
        c("解析销售表格，统计各产品金额，做成透视表", ["DOCUMENT_TABLE_PARSE", "DATA_AGGREGATION_SUMMARY", "DATA_ANALYSIS_PIVOT"], clarify=True, missing=["statistical_range"]),
        c("获取上月销售数据，核算提成，生成凭证", ["DATA_QUERY_FETCH", "RULE_CALCULATION_COMMISSION", "DIGITAL_ASSET_ACCRUAL_VOUCHER"], clarify=True, missing=["calculation_policy"]),
        c("统计各部门费用，按金额排名，生成费用报告", ["DATA_AGGREGATION_SUMMARY", "DATA_SORT", "DOCUMENT_GENERATE"], clarify=True, missing=["statistical_range"]),
        c("查看库存，筛出低库存商品，低于100时提醒我", ["DATA_QUERY_FETCH", "DATA_FILTER", "MONITORING_REMINDER"], clarify=True, missing=["data_source"]),
        c("分析客户投诉，制定改进方案，写一封客户说明邮件", ["DATA_ANALYSIS_PROBLEM", "IMPROVEMENT_PLAN_GENERATE", "CONTENT_GENERATE"]),
        c("查询本月收入，做环比分析，预测下月收入", ["DATA_QUERY_FETCH", "DATA_ANALYSIS_MOM", "DATA_ANALYSIS_FORECAST"], clarify=True, missing=["data_source"]),
        c("从OA获取审批记录，统计超时数量，生成流程优化方案", ["EXTERNAL_DATA_FETCH", "DATA_AGGREGATION_SUMMARY", "IMPROVEMENT_PLAN_GENERATE"], clarify=True, missing=["statistical_range"]),
        c("提取Excel字段，读取销售明细，按渠道求和", ["FILE_STRUCTURE_EXTRACT", "DOCUMENT_TABLE_PARSE", "DATA_ANALYSIS_GROUP_SUM"], clarify=True, missing=["summary_field"]),
        c("了解差旅政策，生成报销说明，再发起报销流程", ["QUESTION_ANSWER", "CONTENT_GENERATE", "WORKFLOW_START"]),
        c("分析新品销售趋势，生成一份报告，再制作一张海报", ["DATA_ANALYSIS_PROBLEM", "DOCUMENT_GENERATE", "MULTIMEDIA_GENERATE"]),
        c("拉取订单数据，找出异常订单，推送到业务系统", ["DATA_QUERY_FETCH", "DATA_FILTER", "EXTERNAL_SYSTEM_SUBMIT"]),
        c("汇总去年利润，做同比和环比分析，形成汇报材料", ["DATA_AGGREGATION_SUMMARY", "DATA_ANALYSIS_YOY", "DATA_ANALYSIS_MOM", "DOCUMENT_GENERATE"], clarify=True, missing=["classification_field"]),
        c("整理客户名单，按贡献度排序，制定维护计划", ["DATA_QUERY_FETCH", "DATA_SORT", "IMPROVEMENT_PLAN_GENERATE"], clarify=True, missing=["data_source"]),
        c("统计各区域回款，筛选逾期客户，设置逾期告警", ["DATA_AGGREGATION_SUMMARY", "DATA_FILTER", "MONITORING_REMINDER"], clarify=True, missing=["statistical_range"]),
        c("分析经营风险，输出应对方案，生成管理层PPT", ["DATA_ANALYSIS_PROBLEM", "IMPROVEMENT_PLAN_GENERATE", "DOCUMENT_GENERATE"]),
        c("从财务系统取费用明细，按部门汇总，再写费用说明", ["EXTERNAL_DATA_FETCH", "DATA_AGGREGATION_SUMMARY", "CONTENT_GENERATE"], clarify=True, missing=["statistical_range"]),
        c("解析合同附件，提取条款结构，筛出到期合同", ["DOCUMENT_TABLE_PARSE", "FILE_STRUCTURE_EXTRACT", "DATA_FILTER"]),
        c("查询合同台账，按到期时间排序，到期前提醒我", ["DATA_QUERY_FETCH", "DATA_SORT", "MONITORING_REMINDER"]),
        c("统计本月投诉数量，分析投诉原因，生成改进计划", ["DATA_AGGREGATION_SUMMARY", "DATA_ANALYSIS_PROBLEM", "IMPROVEMENT_PLAN_GENERATE"]),
        c("获取销售数据，生成透视表，并预测下月趋势", ["DATA_QUERY_FETCH", "DATA_ANALYSIS_PIVOT", "DATA_ANALYSIS_FORECAST"], clarify=True, missing=["statistical_range"]),
        c("读取发票文件，提取字段，生成费用报销说明", ["DOCUMENT_TABLE_PARSE", "FILE_STRUCTURE_EXTRACT", "CONTENT_GENERATE"]),
        c("查询库存记录，过滤低库存，输出补货建议", ["DATA_QUERY_FETCH", "DATA_FILTER", "IMPROVEMENT_PLAN_GENERATE"]),
        c("从ERP拉订单，统计金额，生成订单分析报告", ["EXTERNAL_DATA_FETCH", "DATA_AGGREGATION_SUMMARY", "DOCUMENT_GENERATE"]),
        c("按客户汇总回款，筛出逾期客户，写催款邮件", ["DATA_ANALYSIS_GROUP_SUM", "DATA_FILTER", "CONTENT_GENERATE"], clarify=True, missing=["statistical_range"]),
        c("分析成本波动，预测下季度成本，生成汇报材料", ["DATA_ANALYSIS_PROBLEM", "DATA_ANALYSIS_FORECAST", "DOCUMENT_GENERATE"]),
        c("获取客户资料，做分层排序，生成维护话术", ["DATA_QUERY_FETCH", "DATA_SORT", "CONTENT_GENERATE"]),
        c("查询销售政策，计算提成，生成凭证", ["QUESTION_ANSWER", "RULE_CALCULATION_COMMISSION", "DIGITAL_ASSET_ACCRUAL_VOUCHER"], clarify=True, missing=["sales_data_source"]),
        c("发起采购审批，查询审批状态，写一份进度说明", ["WORKFLOW_START", "DATA_QUERY_FETCH", "CONTENT_GENERATE"], clarify=True, missing=["data_source"]),
    ]


def build_negation_expression() -> list[dict[str, Any]]:
    objects = [
        ("销售情况", "DATA_ANALYSIS_PROBLEM"),
        ("客户名单", "DATA_QUERY_FETCH"),
        ("费用金额", "DATA_AGGREGATION_SUMMARY"),
        ("订单数据", "DATA_QUERY_FETCH"),
        ("库存记录", "DATA_QUERY_FETCH"),
        ("投诉原因", "DATA_ANALYSIS_PROBLEM"),
        ("经营报告", "DOCUMENT_GENERATE"),
        ("销售提成", "RULE_CALCULATION_COMMISSION"),
        ("回款客户", "DATA_FILTER"),
        ("新品海报", "MULTIMEDIA_GENERATE"),
    ]
    cases = []
    for obj, task_type in objects:
        cases.extend(
            [
                c(f"不要生成报告，只分析{obj}", ["DATA_ANALYSIS_PROBLEM"], forbidden=["DOCUMENT_GENERATE"]),
                c(f"本次不需要提醒功能，请处理{obj}", [task_type], forbidden=["MONITORING_REMINDER"]),
                c(f"先不要发起流程，帮我看一下{obj}", [task_type], forbidden=["WORKFLOW_START", "PROCESS_HANDLE"]),
            ]
        )
    return cases[:CATEGORY_SIZE]


def build_future_scope() -> list[dict[str, Any]]:
    scenarios = [
        ("异常情况", "分析销售异常", "DATA_ANALYSIS_PROBLEM"),
        ("客户流失", "分析客户流失原因", "DATA_ANALYSIS_PROBLEM"),
        ("库存不足", "筛选低库存商品", "DATA_FILTER"),
        ("合同到期", "查询合同台账", "DATA_QUERY_FETCH"),
        ("费用超预算", "统计费用金额", "DATA_AGGREGATION_SUMMARY"),
        ("订单超时", "筛选超时订单", "DATA_FILTER"),
        ("回款逾期", "筛选逾期客户", "DATA_FILTER"),
        ("销售波动", "分析销售波动原因", "DATA_ANALYSIS_PROBLEM"),
        ("审批超时", "查询审批记录", "DATA_QUERY_FETCH"),
        ("投诉增长", "分析投诉增长原因", "DATA_ANALYSIS_PROBLEM"),
    ]
    cases = []
    for future_item, current_text, task_type in scenarios:
        cases.extend(
            [
                c(f"以后希望自动提醒{future_item}，但本次不考虑。", [], forbidden=["MONITORING_REMINDER", "提醒"]),
                c(f"未来规划里会做{future_item}监控，目前不包含这部分，当前只需要{current_text}。", [task_type], forbidden=["MONITORING_REMINDER"]),
                c(f"后续可能考虑主动提醒{future_item}，本次不做提醒，只要{current_text}。", [task_type], forbidden=["MONITORING_REMINDER", "主动提醒"]),
            ]
        )
    return cases[:CATEGORY_SIZE]


def build_context_dependency() -> list[dict[str, Any]]:
    seeds = [
        ("计算2025年销售提成", "RULE_CALCULATION_COMMISSION", "帮我再算一遍", "计算", "销售提成"),
        ("生成经营分析报告", "DOCUMENT_GENERATE", "接着改", "生成", "经营分析报告"),
        ("分析销售趋势", "DATA_ANALYSIS_PROBLEM", "换个维度看看", "分析", "销售趋势"),
        ("查询CRM客户资料", "EXTERNAL_DATA_FETCH", "再查一遍", "查询", "客户资料"),
        ("统计本月费用金额", "DATA_AGGREGATION_SUMMARY", "再按部门看看", "统计", "费用金额"),
        ("筛选高风险订单", "DATA_FILTER", "把逾期的也筛出来", "筛选", "高风险订单"),
        ("预测下季度收入", "DATA_ANALYSIS_FORECAST", "利润也预测一下", "预测", "收入"),
        ("起草客户说明邮件", "CONTENT_GENERATE", "语气再正式点", "起草", "客户说明邮件"),
        ("解析销售Excel", "DOCUMENT_TABLE_PARSE", "再看下字段", "解析", "销售Excel"),
        ("办理报销流程", "PROCESS_HANDLE", "再查一下进度", "办理", "报销流程"),
    ]
    cases = []
    for source_text, task_type, current_text, action, obj in seeds:
        history = [{"role": "user", "text": source_text}, {"role": "assistant", "text": "已识别上一轮任务。"}]
        context = {
            "conversation_context": [
                {
                    "task_type": task_type,
                    "task_description": source_text,
                    "source_text": source_text,
                    "action": action,
                    "object": obj,
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
        cases.extend(
            [
                c(current_text, [task_type], history=history, context=context),
                c(f"继续处理：{current_text}", [task_type], history=history, context=context),
                c(f"上一轮那个{current_text}", [task_type], history=history, context=context),
            ]
        )
    return cases[:CATEGORY_SIZE]


def build_insufficient_information() -> list[dict[str, Any]]:
    return [
        c("计算销售提成", ["RULE_CALCULATION_COMMISSION"], clarify=True, missing=["calculation_policy", "sales_data_source"]),
        c("根据规则算一下费用", ["RULE_CALCULATION_GENERAL"], clarify=True, missing=["calculation_basis"]),
        c("把客户数据拿出来", ["DATA_QUERY_FETCH"], clarify=True, missing=["data_source"]),
        c("生成报告", ["DOCUMENT_GENERATE"], clarify=True, missing=["topic"]),
        c("发起审批", ["WORKFLOW_START"], clarify=True, missing=["process_name"]),
        c("低于阈值时提醒我", ["MONITORING_REMINDER"], clarify=True, missing=["monitoring_object", "trigger_condition"]),
        c("做个统计", ["DATA_AGGREGATION_SUMMARY"], clarify=True, missing=["summary_field", "statistical_range"]),
        c("帮我排序", ["DATA_SORT"], clarify=True, missing=["data_source"]),
        c("筛选异常", ["DATA_FILTER"], clarify=True, missing=["data_source"]),
        c("写一封邮件", ["CONTENT_GENERATE"], clarify=True, missing=["topic"]),
        c("做个方案", ["IMPROVEMENT_PLAN_GENERATE"], clarify=True, missing=["topic"]),
        c("生成一张图片", ["MULTIMEDIA_GENERATE"], clarify=True, missing=["topic"]),
        c("解析附件", ["DOCUMENT_TABLE_PARSE"], clarify=True, missing=["file"]),
        c("提取字段", ["FILE_STRUCTURE_EXTRACT"], clarify=True, missing=["file"]),
        c("查询系统数据", ["EXTERNAL_DATA_FETCH"], clarify=True, missing=["external_system"]),
        c("回写结果", ["EXTERNAL_SYSTEM_SUBMIT"], clarify=True, missing=["external_system"]),
        c("做同比", ["DATA_ANALYSIS_YOY"], clarify=True, missing=["summary_field", "statistical_range"]),
        c("做环比", ["DATA_ANALYSIS_MOM"], clarify=True, missing=["summary_field", "statistical_range"]),
        c("预测一下", ["DATA_ANALYSIS_FORECAST"], clarify=True, missing=["analysis_object"]),
        c("分析一下", ["DATA_ANALYSIS_PROBLEM"], clarify=True, missing=["analysis_object"]),
        c("生成凭证", ["DIGITAL_ASSET_ACCRUAL_VOUCHER"], clarify=True, missing=["source_result"]),
        c("办理流程", ["PROCESS_HANDLE"], clarify=True, missing=["process_name"]),
        c("回答这个问题", [], clarify=True),
        c("继续弄", [], clarify=True),
        c("再处理一下", [], clarify=True),
        c("那个也做一下", [], clarify=True),
        c("帮我看一下", [], clarify=True),
        c("把它整理一下", [], clarify=True),
        c("按之前的来", [], clarify=True),
        c("这个结果再弄一下", [], clarify=True),
    ]


def build_ambiguous_request() -> list[dict[str, Any]]:
    texts = [
        "处理一下",
        "帮我弄一下",
        "这个怎么搞",
        "照之前那样",
        "继续",
        "接着来",
        "看一下这个",
        "帮我优化一下",
        "这个不太对",
        "再来一版",
        "把那个做了",
        "按领导说的处理",
        "帮我看看",
        "搞定它",
        "这件事推进一下",
        "结果有点问题",
        "还是不行",
        "再调整",
        "按方案来",
        "处理这些材料",
        "看看有没有问题",
        "照旧",
        "继续上面的",
        "把这块弄完",
        "下一步怎么做",
        "帮忙跟一下",
        "这个先放一放",
        "都处理掉",
        "给我一个结果",
        "你看着办",
    ]
    return [c(text, [], clarify=True) for text in texts]


CATEGORY_BUILDERS = [
    ("short_instruction", build_short_instruction),
    ("long_text_requirement", build_long_requirement),
    ("colloquial_expression", build_colloquial_expression),
    ("omitted_expression", build_omitted_expression),
    ("multi_task_request", build_multi_task_request),
    ("negation_expression", build_negation_expression),
    ("future_scope", build_future_scope),
    ("context_dependency", build_context_dependency),
    ("insufficient_information", build_insufficient_information),
    ("ambiguous_request", build_ambiguous_request),
]


if __name__ == "__main__":
    raise SystemExit(main())

