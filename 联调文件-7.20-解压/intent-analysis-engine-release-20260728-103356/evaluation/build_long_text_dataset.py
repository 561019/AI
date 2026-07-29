from __future__ import annotations

import json
from pathlib import Path


OUTPUT_PATH = Path(__file__).with_name("long_text_dataset.json")


SCENARIOS = [
    {
        "request": "请查询今年各区域销售数据。",
        "actions": ["query"],
        "tasks": ["DATA_QUERY_FETCH"],
        "engines": ["ENG_DATA_COLLECTION_AGGREGATION"],
        "clarify": False,
    },
    {
        "request": "请分析今年各区域销售表现。",
        "actions": ["analyze"],
        "tasks": ["DATA_ANALYSIS_PROBLEM"],
        "engines": ["ENG_ANALYTICS_FORECASTING"],
        "clarify": False,
    },
    {
        "request": "请分析上个月华东销售下降原因，然后生成管理层报告。",
        "actions": ["analyze", "generate"],
        "tasks": ["DATA_ANALYSIS_PROBLEM", "DOCUMENT_GENERATE"],
        "engines": ["ENG_ANALYTICS_FORECASTING", "ENG_CONTENT_OUTPUT"],
        "clarify": False,
    },
    {
        "request": "请从CRM获取本季度客户资料，再筛选高价值客户。",
        "actions": ["query", "filter"],
        "tasks": ["EXTERNAL_DATA_FETCH", "DATA_FILTER"],
        "engines": ["ENG_EXTERNAL_SYSTEM_CONNECTOR", "ENG_DATA_COLLECTION_AGGREGATION"],
        "clarify": False,
    },
    {
        "request": "请读取上传的销售Excel，按区域汇总销售金额。",
        "actions": ["parse", "organize"],
        "tasks": ["DOCUMENT_TABLE_PARSE", "DATA_AGGREGATION_SUMMARY"],
        "engines": ["ENG_DOCUMENT_TABLE_PARSING", "ENG_DATA_COLLECTION_AGGREGATION"],
        "clarify": True,
    },
    {
        "request": "请查询上个月销售明细，根据现行提成政策计算销售提成，再生成计提凭证。",
        "actions": ["query", "calculate", "generate"],
        "tasks": ["DATA_QUERY_FETCH", "RULE_CALCULATION_COMMISSION", "DIGITAL_ASSET_ACCRUAL_VOUCHER"],
        "engines": ["ENG_DATA_COLLECTION_AGGREGATION", "ENG_RULE_CALCULATION", "ENG_DIGITAL_ASSET"],
        "clarify": False,
    },
    {
        "request": "请查询本月库存记录，筛选低于安全值的商品，并设置每天提醒。",
        "actions": ["query", "filter", "monitor"],
        "tasks": ["DATA_QUERY_FETCH", "DATA_FILTER", "MONITORING_REMINDER"],
        "engines": ["ENG_DATA_COLLECTION_AGGREGATION", "ENG_DATA_COLLECTION_AGGREGATION", "ENG_MONITORING_REMINDER"],
        "clarify": False,
    },
    {
        "request": "请统计今年各渠道销售额，按金额排序，再预测下季度销售趋势。",
        "actions": ["organize", "sort", "forecast"],
        "tasks": ["DATA_AGGREGATION_SUMMARY", "DATA_SORT", "DATA_ANALYSIS_FORECAST"],
        "engines": ["ENG_DATA_COLLECTION_AGGREGATION", "ENG_DATA_COLLECTION_AGGREGATION", "ENG_ANALYTICS_FORECASTING"],
        "clarify": False,
    },
    {
        "request": "请整理今年客户投诉记录，分析投诉增加原因，最后生成改进方案。",
        "actions": ["organize", "analyze", "generate"],
        "tasks": ["COMPLAINT_INFORMATION_ORGANIZE", "DATA_ANALYSIS_PROBLEM", "IMPROVEMENT_PLAN_GENERATE"],
        "engines": ["ENG_DATA_COLLECTION_AGGREGATION", "ENG_ANALYTICS_FORECASTING", "ENG_CONTENT_OUTPUT"],
        "clarify": False,
    },
    {
        "request": "请统计去年各产品利润，做同比分析，最后生成管理层材料。",
        "actions": ["organize", "compare", "generate"],
        "tasks": ["DATA_AGGREGATION_SUMMARY", "DATA_ANALYSIS_YOY", "DOCUMENT_GENERATE"],
        "engines": ["ENG_DATA_COLLECTION_AGGREGATION", "ENG_ANALYTICS_FORECASTING", "ENG_CONTENT_OUTPUT"],
        "clarify": False,
    },
    {
        "request": "请从ERP获取采购订单，筛选未完成记录，再推送到OA系统。",
        "actions": ["query", "filter", "sync"],
        "tasks": ["EXTERNAL_DATA_FETCH", "DATA_FILTER", "EXTERNAL_SYSTEM_SUBMIT"],
        "engines": ["ENG_EXTERNAL_SYSTEM_CONNECTOR", "ENG_DATA_COLLECTION_AGGREGATION", "ENG_EXTERNAL_SYSTEM_CONNECTOR"],
        "clarify": False,
    },
    {
        "request": "请分析本季度订单下降原因，并生成流程改进方案。",
        "actions": ["analyze", "generate"],
        "tasks": ["DATA_ANALYSIS_PROBLEM", "IMPROVEMENT_PLAN_GENERATE"],
        "engines": ["ENG_ANALYTICS_FORECASTING", "ENG_CONTENT_OUTPUT"],
        "clarify": False,
    },
    {
        "request": "请发起采购审批流程。",
        "actions": ["process"],
        "tasks": ["WORKFLOW_START"],
        "engines": ["ENG_WORKFLOW_EXECUTION"],
        "clarify": False,
    },
    {
        "request": "请解析上传的合同附件，再提取条款字段。",
        "actions": ["parse", "parse"],
        "tasks": ["DOCUMENT_TABLE_PARSE", "FILE_STRUCTURE_EXTRACT"],
        "engines": ["ENG_DOCUMENT_TABLE_PARSING", "ENG_DOCUMENT_TABLE_PARSING"],
        "clarify": False,
    },
    {
        "request": "请监控合同到期日期，并在到期前七天提醒我。",
        "actions": ["monitor"],
        "tasks": ["MONITORING_REMINDER"],
        "engines": ["ENG_MONITORING_REMINDER"],
        "clarify": False,
    },
    {
        "request": "请生成一份员工差旅报销通知。",
        "actions": ["generate"],
        "tasks": ["CONTENT_GENERATE"],
        "engines": ["ENG_CONTENT_OUTPUT"],
        "clarify": False,
    },
    {
        "request": "请生成一张新品宣传海报。",
        "actions": ["generate"],
        "tasks": ["MULTIMEDIA_GENERATE"],
        "engines": ["ENG_MULTIMEDIA_GENERATION"],
        "clarify": False,
    },
    {
        "request": "请筛选回款逾期超过三十天的客户。",
        "actions": ["filter"],
        "tasks": ["DATA_FILTER"],
        "engines": ["ENG_DATA_COLLECTION_AGGREGATION"],
        "clarify": False,
    },
    {
        "request": "请按销售金额从高到低排序客户名单。",
        "actions": ["sort"],
        "tasks": ["DATA_SORT"],
        "engines": ["ENG_DATA_COLLECTION_AGGREGATION"],
        "clarify": False,
    },
    {
        "request": "请预测明年各区域销售额趋势。",
        "actions": ["forecast"],
        "tasks": ["DATA_ANALYSIS_FORECAST"],
        "engines": ["ENG_ANALYTICS_FORECASTING"],
        "clarify": False,
    },
]


def render_text(category: str, request: str, index: int) -> str:
    if category == "业务邮件":
        return (
            "主题：经营工作协同。各位同事好，公司正在推进年度经营复盘，前期材料已经完成收集，"
            "这部分只是背景说明，不需要重复处理。"
            f"本次邮件需要落实以下事项：{request}完成后请保留原始口径，谢谢。"
        )
    if category == "会议纪要":
        return (
            "会议纪要：会上回顾了近期业务情况，与会人员讨论了进度和风险，以上内容仅作记录。"
            "此前团队已经整理了基础说明，不需要再次创建相同任务。"
            f"会议形成的明确行动项是：{request}责任人后续根据任务清单推进。"
        )
    if category == "用户需求描述":
        return (
            "业务背景：当前部门正在优化日常管理方式，现状、历史沿革和人员分工仅用于帮助理解场景。"
            "需求边界：不得猜测数据来源或业务规则，也不要执行未明确提出的操作。"
            f"用户明确目标：{request}输出应保持任务之间的先后关系。"
        )
    if category == "聊天记录":
        return (
            "业务同事：最近事情有点多，领导问了几次进展。产品同事：收到，这些只是背景，不作为任务。"
            f"业务同事：麻烦按这个明确要求处理，{request}产品同事：好的，先识别任务，不执行业务。"
        )
    filler = (
        "项目启动以来，团队持续讨论组织安排、沟通节奏和历史材料。"
        "这些段落用于说明背景，不包含新的执行动作，也不代表需要处理其中提到的业务对象。"
        "此前已经完成的准备工作无需重复，情绪和时间压力也不应改变任务判断。"
    )
    return filler * (8 + index % 3) + f"全文唯一明确的任务要求如下：{request}" + filler * 2


def build_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    categories = ["业务邮件", "会议纪要", "用户需求描述", "聊天记录", "大量背景文本"]
    for category_index, category in enumerate(categories):
        for scenario_index, scenario in enumerate(SCENARIOS):
            case_number = category_index * len(SCENARIOS) + scenario_index + 1
            cases.append(
                {
                    "id": f"long-{case_number:03d}",
                    "category": category,
                    "text": render_text(category, str(scenario["request"]), scenario_index),
                    "expected_actions": scenario["actions"],
                    "expected_tasks": scenario["tasks"],
                    "expected_engine": scenario["engines"],
                    "should_clarify": scenario["clarify"],
                }
            )
    return cases


def main() -> int:
    OUTPUT_PATH.write_text(
        json.dumps(build_cases(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(build_cases())} cases to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
